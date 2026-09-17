"""Chessathon pure Python engine. No runtime file access or dependencies but chess.

Public interface: get_move(fen: str, time_left_ms: int) -> str.
Only positions without a legal move return "0000".
"""
import math
import time
from collections import deque
import chess

INF = 32000
MATE = 30000
MATE_BOUND = 29000
MAX_PLY = 100
TT_LIMIT = 180000
MG_VALUE = (0, 100, 325, 340, 505, 975, 0)
EG_VALUE = (0, 120, 310, 335, 530, 950, 0)
PHASE = (0, 0, 1, 1, 2, 4, 0)
CAP_VALUE = (0, 100, 320, 335, 510, 975, 20000)
BB = chess.BB_SQUARES
FILES = chess.BB_FILES
RANKS = chess.BB_RANKS
NEIGHBOUR_FILES = [(FILES[f - 1] if f else 0) | (FILES[f + 1] if f < 7 else 0) for f in range(8)]
scan = chess.scan_forward
clock = time.perf_counter


def _make_tables():
    # Original, formula-generated PSTs; no published engine tables or code.
    mg = [[0] * 64 for _ in range(14)]
    eg = [[0] * 64 for _ in range(14)]
    for color in (0, 1):
        sign = 1 if color else -1
        for pt in range(1, 7):
            for sq in range(64):
                f = sq & 7
                r = (sq >> 3) if color else 7 - (sq >> 3)
                center = abs(f - 3.5) + abs(r - 3.5)
                if pt == chess.PAWN:
                    m = r * 5 - abs(f - 3.5) * 4
                    m += 12 if f in (3, 4) and r in (2, 3, 4) else 0
                    e = r * 8 - abs(f - 3.5) * 2
                elif pt == chess.KNIGHT:
                    m = 42 - 14 * center - (18 if r == 0 else 0)
                    e = 30 - 10 * center
                elif pt == chess.BISHOP:
                    m = 22 - 5 * center - (12 if r == 0 else 0)
                    e = 20 - 4 * center
                elif pt == chess.ROOK:
                    m = (20 if r == 6 else 0) + r * 2 - abs(f - 3.5)
                    e = (15 if r == 6 else 0) + r * 2
                elif pt == chess.QUEEN:
                    m = 8 - 3 * center - (8 if r > 2 else 0)
                    e = 20 - 4 * center
                else:
                    m = -r * 16 + abs(f - 3.5) * 8
                    m += 22 if r == 0 and f in (1, 2, 6) else 0
                    e = 55 - 14 * center
                index = color * 7 + pt
                mg[index][sq] = sign * int(MG_VALUE[pt] + m)
                eg[index][sq] = sign * int(EG_VALUE[pt] + e)
    return mg, eg


MG, EG = _make_tables()
PASSED = [[0] * 64 for _ in range(2)]
FORWARD = [[0] * 64 for _ in range(2)]
for _color in (0, 1):
    for _sq in range(64):
        _f, _r = _sq & 7, _sq >> 3
        _mask = FILES[_f]
        if _f:
            _mask |= FILES[_f - 1]
        if _f < 7:
            _mask |= FILES[_f + 1]
        _ahead = 0
        for _rank in (range(_r + 1, 8) if _color else range(_r)):
            _ahead |= RANKS[_rank]
        PASSED[_color][_sq] = _mask & _ahead
        FORWARD[_color][_sq] = FILES[_f] & _ahead
PASS_MG = (0, 0, 6, 12, 24, 45, 80, 0)
PASS_EG = (0, 0, 12, 25, 50, 95, 170, 0)
LMR = [[0] * 64 for _ in range(64)]
for _d in range(3, 64):
    for _n in range(3, 64):
        LMR[_d][_n] = max(1, int(math.log(_d) * math.log(_n) / 2.5))


def _key(board):
    """Counter-free identity, with en passant included only when legal."""
    method = getattr(board, "_transposition_key", None)
    if method is not None:
        return method()
    return (board.pawns, board.knights, board.bishops, board.rooks,
            board.queens, board.kings, board.occupied_co[1],
            board.occupied_co[0], board.turn, board.clean_castling_rights(),
            board.ep_square if board.has_legal_en_passant() else None)


def _base_eval(board):
    mg = eg = phase = 0
    for color in (0, 1):
        for pt in range(1, 7):
            mask = board.pieces_mask(pt, color)
            phase += mask.bit_count() * PHASE[pt]
            mgt, egt = MG[color * 7 + pt], EG[color * 7 + pt]
            for sq in scan(mask):
                mg += mgt[sq]
                eg += egt[sq]
    return mg, eg, phase


def _allocate(time_left_ms, increment_ms=500):
    """Return soft and hard seconds, without borrowing the next increment."""
    remaining = max(0.0, float(time_left_ms)) / 1000.0
    inc = max(0.0, float(increment_ms)) / 1000.0
    usable = max(0.0, remaining - 0.150)
    if remaining < 0.100:
        return 0.0, 0.0
    if remaining < 0.500:
        hard = min(0.025, usable * 0.12)
        return hard * 0.65, hard
    if remaining < 1.5:
        hard = min(0.140, usable * 0.18)
        return hard * 0.70, hard
    soft = remaining / 35.0 + inc * 0.75
    hard = min(1.6 * soft, remaining / 8.0, usable)
    return min(soft, hard), hard


class _Timeout(Exception):
    pass


class _Game:
    def __init__(self):
        self.tt = {}
        self.tt_order = deque()
        self.pawn_cache = {}
        self.history = [[0] * 4096 for _ in range(2)]
        self.killers = [[None, None] for _ in range(MAX_PLY + 2)]
        self.seen = []
        self.root_history = []
        self.pre_key = None
        self.after = None
        self.our_zeroing = False
        self.last_rights = None
        self.epoch = 0
        self.generation = 0
        self.last_stats = {}
        self.exceptions = 0

    def reset(self):
        self.tt.clear()
        self.tt_order.clear()
        self.pawn_cache.clear()
        self.history = [[0] * 4096 for _ in range(2)]
        self.killers = [[None, None] for _ in range(MAX_PLY + 2)]
        self.seen = []
        self.root_history = []
        self.pre_key = None
        self.after = None
        self.our_zeroing = False
        self.last_rights = None
        self.epoch += 1

    def observe(self, board):
        key = _key(board)
        if self.pre_key == key:
            return "retry"
        rights = board.clean_castling_rights()
        if board.halfmove_clock == 0 or (self.last_rights is not None and rights != self.last_rights):
            self.seen.clear()
        self.seen.append(key)
        keep = max(1, board.halfmove_clock + 1)
        if len(self.seen) > keep:
            self.seen = self.seen[-keep:]
        self.root_history = self.seen[:]
        self.pre_key = key
        self.last_rights = rights
        self.generation += 1
        return "recorded"

    def retain(self, board, move):
        self.pre_key = _key(board)
        self.our_zeroing = board.is_zeroing(move)
        self.seen = [] if self.our_zeroing else self.root_history[:]
        board.push(move)
        rights = board.clean_castling_rights()
        if rights != self.last_rights:
            self.seen.clear()
        self.last_rights = rights
        self.seen.append(_key(board))
        self.after = board


_GAME = _Game()


class _Search:
    def __init__(self, board, game, deadline, soft_deadline):
        self.b = board
        self.game = game
        self.tt = game.tt
        self.tt_order = game.tt_order
        self.pawn_cache = game.pawn_cache
        self.history = game.history
        self.killers = game.killers
        self.mg, self.eg, self.phase = _base_eval(board)
        self.deadline = deadline
        self.soft_deadline = soft_deadline
        self.nodes = self.qnodes = self.hits = self.probes = 0
        self.path = []
        self.prior = {}
        for key in game.root_history[:-1]:
            self.prior[key] = self.prior.get(key, 0) + 1
        self.root_color = board.turn
        base = self.evaluate()
        self.contempt = -min(100, max(15, base // 5)) if base > 80 else (35 if base < -150 else 0)
        self.partial_move = None
        self.partial_score = -INF
        self.iterations = []
        self.started = clock()
        self.check_mask = 31 if deadline - self.started < 0.15 else 255

    def tick(self, q=False):
        if q:
            self.qnodes += 1
        else:
            self.nodes += 1
        if ((self.nodes + self.qnodes) & self.check_mask) == 0 and clock() >= self.deadline:
            raise _Timeout

    def draw_score(self):
        return self.contempt if self.b.turn == self.root_color else -self.contempt

    def repeated(self, key):
        # Both collections exclude this node: two previous occurrences make
        # the current occurrence the third. A second occurrence is not a draw.
        return self.prior.get(key, 0) + self.path.count(key) >= 2

    def play(self, move):
        b = self.b
        color = b.turn
        pt = b.piece_type_at(move.from_square)
        ci = color * 7 + pt
        frm, to = move.from_square, move.to_square
        self.mg += MG[ci][to] - MG[ci][frm]
        self.eg += EG[ci][to] - EG[ci][frm]
        captured = b.piece_type_at(to)
        cap_sq = to
        if pt == chess.PAWN and to == b.ep_square and not captured:
            cap_sq = to - 8 if color else to + 8
            captured = chess.PAWN
        if captured:
            ci = (not color) * 7 + captured
            self.mg -= MG[ci][cap_sq]
            self.eg -= EG[ci][cap_sq]
            self.phase -= PHASE[captured]
        if move.promotion:
            pi, qi = color * 7 + chess.PAWN, color * 7 + move.promotion
            self.mg += MG[qi][to] - MG[pi][to]
            self.eg += EG[qi][to] - EG[pi][to]
            self.phase += PHASE[move.promotion]
        if pt == chess.KING and abs(to - frm) == 2:
            rf = frm + 3 if to > frm else frm - 4
            rt = frm + 1 if to > frm else frm - 1
            ri = color * 7 + chess.ROOK
            self.mg += MG[ri][rt] - MG[ri][rf]
            self.eg += EG[ri][rt] - EG[ri][rf]
        b.push(move)

    def evaluate(self):
        b = self.b
        mg, eg = self.mg, self.eg
        phase = min(24, self.phase)
        white, black = b.occupied_co[1], b.occupied_co[0]
        pawns = b.pawns
        wp, bp = pawns & white, pawns & black
        pawnkey = (wp, bp)
        pawninfo = self.pawn_cache.get(pawnkey)
        if pawninfo is None:
            pmg = peg = passed_white = passed_black = 0
            for color, own, enemy, sign in ((1, wp, bp, 1), (0, bp, wp, -1)):
                for sq in scan(own):
                    file = sq & 7
                    rank = (sq >> 3) if color else 7 - (sq >> 3)
                    if not (PASSED[color][sq] & enemy) and not (FORWARD[color][sq] & own):
                        pmg += sign * PASS_MG[rank]
                        peg += sign * PASS_EG[rank]
                        if color:
                            passed_white |= BB[sq]
                        else:
                            passed_black |= BB[sq]
                    if not (NEIGHBOUR_FILES[file] & own):
                        pmg -= sign * 10
                        peg -= sign * 8
                    if FORWARD[color][sq] & own:
                        pmg -= sign * 10
                        peg -= sign * 15
            pawninfo = pmg, peg, passed_white, passed_black
            if len(self.pawn_cache) >= 16384:
                self.pawn_cache.clear()
            self.pawn_cache[pawnkey] = pawninfo
        mg += pawninfo[0]
        eg += pawninfo[1]
        for sq in scan(pawninfo[2] & ~(b.occupied >> 8)):
            eg += PASS_EG[sq >> 3] // 4
        for sq in scan(pawninfo[3] & ~(b.occupied << 8)):
            eg -= PASS_EG[7 - (sq >> 3)] // 4
        for color, occ, own, enemy, sign in ((1, white, wp, bp, 1), (0, black, bp, wp, -1)):
            bishops = b.bishops & occ
            if bishops & (bishops - 1):
                mg += sign * 28
                eg += sign * 40
            for sq in scan(b.rooks & occ):
                filemask = FILES[sq & 7]
                if not (filemask & own):
                    mg += sign * (20 if not filemask & enemy else 10)
                    eg += sign * 8
            if phase > 10:
                king = b.king(color)
                if king is not None:
                    shield_rank = (king >> 3) + (1 if color else -1)
                    if 0 <= shield_rank < 8:
                        shield = chess.BB_KING_ATTACKS[king] & RANKS[shield_rank] & own
                        mg += sign * shield.bit_count() * 11
                        if not (FILES[king & 7] & own):
                            mg -= sign * 22
        score = (mg * phase + eg * (24 - phase)) // 24
        if not pawns and phase <= 8:
            wn = white & ~b.kings
            bn = black & ~b.kings
            if not wn or not bn:
                strong = 1 if wn else 0
                force = wn if wn else bn
                major = force & (b.rooks | b.queens)
                minors = force & (b.knights | b.bishops)
                if not major and minors.bit_count() < 2:
                    return 0
                if not major and not (force & b.bishops):
                    return 0
                wk, bk = b.king(strong), b.king(not strong)
                if wk is not None and bk is not None:
                    edge = max(abs((bk & 7) * 2 - 7), abs((bk >> 3) * 2 - 7))
                    distance = max(abs((wk & 7) - (bk & 7)), abs((wk >> 3) - (bk >> 3)))
                    score += (1 if strong else -1) * (edge * 22 + (7 - distance) * 24)
            elif not (b.rooks | b.queens) and (wn | bn).bit_count() <= 2:
                score //= 8
        if b.halfmove_clock > 70:
            score = score * max(0, 100 - b.halfmove_clock) // 30
        return (score if b.turn else -score) + 12

    def move_score(self, move, ttmove, ply):
        if move == ttmove:
            return 2000000
        b = self.b
        victim = b.piece_type_at(move.to_square)
        attacker = b.piece_type_at(move.from_square)
        if victim or (attacker == chess.PAWN and move.to_square == b.ep_square):
            return 1000000 + CAP_VALUE[victim or chess.PAWN] * 16 - CAP_VALUE[attacker] + CAP_VALUE[move.promotion or 0]
        if move.promotion:
            return 900000 + CAP_VALUE[move.promotion]
        killers = self.killers[ply]
        if move == killers[0]:
            return 800000
        if move == killers[1]:
            return 799000
        return self.history[b.turn][move.from_square * 64 + move.to_square]

    def store(self, key, depth, score, flag, move, ply):
        if score > MATE_BOUND:
            score += ply
        elif score < -MATE_BOUND:
            score -= ply
        old = self.tt.get(key)
        if old is None or depth >= old[0] - 2 or old[5] != self.game.generation:
            if len(self.tt) >= TT_LIMIT and old is None:
                self.tt.pop(self.tt_order.popleft(), None)
            if old is None:
                self.tt_order.append(key)
            self.tt[key] = (depth, score, flag, move, self.b.halfmove_clock, self.game.generation)

    def qsearch(self, alpha, beta, ply, qdepth=0, null_tree=False):
        self.tick(True)
        b = self.b
        check = b.is_check()
        if ply >= MAX_PLY:
            if check and not any(b.generate_legal_moves()):
                return -MATE + ply
            return self.evaluate()
        key = _key(b)
        if not null_tree and (self.repeated(key) or b.halfmove_clock >= 100):
            if check and not any(b.generate_legal_moves()):
                return -MATE + ply
            return self.draw_score()
        if check:
            moves = list(b.generate_legal_moves())
            if not moves:
                return -MATE + ply
            best = -INF
        else:
            if not any(b.generate_legal_moves()):
                return self.draw_score()
            best = self.evaluate()
            if best >= beta:
                return best
            if best > alpha:
                alpha = best
            if qdepth >= 20:
                return best
            moves = list(b.generate_legal_captures())
            promotion_rank = RANKS[6 if b.turn else 1]
            if b.pawns & b.occupied_co[b.turn] & promotion_rank:
                for move in b.generate_legal_moves(from_mask=promotion_rank & b.pawns, to_mask=~b.occupied):
                    if move.promotion:
                        moves.append(move)
        moves.sort(key=lambda m: self.move_score(m, None, ply), reverse=True)
        mg, eg, phase = self.mg, self.eg, self.phase
        self.path.append(key)
        try:
            for move in moves:
                if not check and not move.promotion and best > -MATE_BOUND:
                    victim = b.piece_type_at(move.to_square) or chess.PAWN
                    if best + CAP_VALUE[victim] + 240 < alpha:
                        continue
                self.play(move)
                try:
                    score = -self.qsearch(-beta, -alpha, ply + 1, qdepth + 1, null_tree)
                finally:
                    b.pop()
                    self.mg, self.eg, self.phase = mg, eg, phase
                if score > best:
                    best = score
                if score > alpha:
                    alpha = score
                    if alpha >= beta:
                        break
        finally:
            self.path.pop()
        return best

    def search(self, depth, alpha, beta, ply, allow_null=True, null_tree=False):
        if depth <= 0:
            return self.qsearch(alpha, beta, ply, null_tree=null_tree)
        self.tick()
        b = self.b
        check = b.is_check()
        if ply >= MAX_PLY:
            return self.qsearch(alpha, beta, ply, null_tree=null_tree)
        key = _key(b)
        repeat_count = self.prior.get(key, 0) + self.path.count(key)
        if ply and not null_tree and (self.repeated(key) or b.halfmove_clock >= 100):
            if check and not any(b.generate_legal_moves()):
                return -MATE + ply
            return self.draw_score()
        original_alpha = alpha
        pv = beta - alpha > 1
        ttmove = None
        self.probes += 1
        entry = self.tt.get(key)
        if entry is not None:
            self.hits += 1
            ttmove = entry[3]
            score = entry[1]
            if score > MATE_BOUND:
                score -= ply
            elif score < -MATE_BOUND:
                score += ply
            if (ply and not pv and not repeat_count and not null_tree
                    and entry[0] >= depth and entry[4] == b.halfmove_clock):
                if entry[2] == 0 or (entry[2] == 1 and score >= beta) or (entry[2] == 2 and score <= alpha):
                    return score
        static = self.evaluate() if not check else -INF
        nonpawns = b.occupied_co[b.turn] & ~(b.pawns | b.kings)
        if (allow_null and not null_tree and not pv and not check and depth >= 3
                and nonpawns and static >= beta and beta < MATE_BOUND
                and b.halfmove_clock < 90 and any(b.generate_legal_moves())):
            b.push(chess.Move.null())
            try:
                reduction = 2 + depth // 5
                score = -self.search(depth - reduction - 1, -beta, -beta + 1,
                                     ply + 1, False, True)
            finally:
                b.pop()
            if score >= beta:
                return min(score, MATE_BOUND - 1)
        moves = list(b.generate_legal_moves())
        if not moves:
            return -MATE + ply if check else self.draw_score()
        moves.sort(key=lambda m: self.move_score(m, ttmove, ply), reverse=True)
        mg, eg, phase = self.mg, self.eg, self.phase
        best, bestmove = -INF, None
        color = b.turn
        quiets = []
        self.path.append(key)
        try:
            for index, move in enumerate(moves):
                if ply == 0 and clock() >= self.deadline:
                    raise _Timeout
                capture = bool(b.occupied_co[not color] & BB[move.to_square]) or (b.pawns & BB[move.from_square] and move.to_square == b.ep_square)
                quiet = not capture and not move.promotion
                self.play(move)
                try:
                    gives_check = b.is_check()
                    extension = 1 if gives_check and depth <= 6 else 0
                    if ply > 2 * depth + 8:
                        extension = 0
                    childdepth = depth - 1 + extension
                    reduction = 0
                    if (index >= 3 and depth >= 3 and quiet and not check and not gives_check
                            and move not in self.killers[ply]):
                        reduction = LMR[min(depth, 63)][min(index + 1, 63)]
                        if pv:
                            reduction = max(1, reduction - 1)
                        reduction = min(reduction, max(0, childdepth - 1))
                    if index == 0:
                        score = -self.search(childdepth, -beta, -alpha, ply + 1, True, null_tree)
                    else:
                        score = -self.search(childdepth - reduction, -alpha - 1, -alpha, ply + 1, True, null_tree)
                        if reduction and score > alpha:
                            score = -self.search(childdepth, -alpha - 1, -alpha, ply + 1, True, null_tree)
                        if score > alpha and score < beta:
                            score = -self.search(childdepth, -beta, -alpha, ply + 1, True, null_tree)
                finally:
                    b.pop()
                    self.mg, self.eg, self.phase = mg, eg, phase
                if score > best:
                    best, bestmove = score, move
                    if ply == 0:
                        self.partial_move, self.partial_score = move, score
                if score > alpha:
                    alpha = score
                    if alpha >= beta:
                        if quiet:
                            killers = self.killers[ply]
                            if move != killers[0]:
                                killers[1], killers[0] = killers[0], move
                            history = self.history[color]
                            slot = move.from_square * 64 + move.to_square
                            bonus = min(2000, depth * depth * 16)
                            history[slot] += bonus - history[slot] * bonus // 16000
                            for old in quiets:
                                slot = old.from_square * 64 + old.to_square
                                history[slot] -= bonus + history[slot] * bonus // 16000
                        break
                if quiet:
                    quiets.append(move)
        finally:
            self.path.pop()
        if not null_tree and not repeat_count:
            flag = 1 if best >= beta else (2 if best <= original_alpha else 0)
            self.store(key, depth, best, flag, bestmove, ply)
        return best

    def run(self, legal):
        move = legal[0]
        score = -INF
        depth_done = 0
        durations = []
        changes = 0
        for depth in range(1, 64):
            now = clock()
            if depth > 1:
                if now >= self.soft_deadline:
                    break
                if durations:
                    growth = durations[-1] / max(durations[-2], 0.001) if len(durations) > 1 else 3.0
                    predicted = durations[-1] * min(5.0, max(1.7, growth))
                    if now + predicted * 0.70 >= self.deadline:
                        break
            self.partial_move, self.partial_score = None, -INF
            iteration_start = clock()
            oldmove, oldscore = move, score
            try:
                if depth >= 4 and abs(score) < MATE_BOUND:
                    window = 35
                    low, high = score - window, score + window
                    while True:
                        value = self.search(depth, low, high, 0)
                        if value <= low:
                            low -= window
                        elif value >= high:
                            high += window
                        else:
                            break
                        window *= 2
                        if window > 1000:
                            low, high = -INF, INF
                else:
                    value = self.search(depth, -INF, INF, 0)
                if self.partial_move is not None:
                    move, score = self.partial_move, value
                depth_done = depth
            except _Timeout:
                if self.partial_move is not None and self.partial_score > score:
                    move, score = self.partial_move, self.partial_score
                break
            elapsed = clock() - iteration_start
            durations.append(elapsed)
            changed = oldmove != move
            if changed and depth > 1:
                changes += 1
            self.iterations.append({"depth": depth, "score": score, "move": move.uci(),
                                    "seconds": round(elapsed, 5), "changed": changed})
            if depth >= 3 and (changed or score < oldscore - 70):
                self.soft_deadline = min(self.deadline, self.soft_deadline + elapsed * 0.5)
            if score > MATE_BOUND and depth >= MATE - score:
                break
        elapsed = clock() - self.started
        return move, {"move": move.uci(), "score": score, "depth": depth_done,
                      "nodes": self.nodes, "qnodes": self.qnodes,
                      "nps": int((self.nodes + self.qnodes) / max(elapsed, 0.000001)),
                      "wall": elapsed, "tt_hit_rate": self.hits / max(1, self.probes),
                      "best_move_changes": changes, "iterations": self.iterations,
                      "tt_entries": len(self.tt)}


def _analyse(fen, seconds=2.5):
    """In-memory diagnostic hook; no files or working-directory dependence."""
    board = chess.Board(fen)
    game = _Game()
    game.observe(board)
    legal = list(board.generate_legal_moves())
    if not legal:
        return {"move": "0000", "depth": 0}
    start = clock()
    search = _Search(board, game, start + seconds, start + seconds * 0.90)
    _, stats = search.run(legal)
    return stats


def get_move(fen: str, time_left_ms: int) -> str:
    """Return a legal UCI move for every position that has legal moves."""
    start = clock()
    board = None
    fallback = None
    try:
        board = chess.Board(fen)
        fallback = next(board.generate_legal_moves(), None)
        if fallback is None:
            return "0000"
        _GAME.observe(board)
        soft, hard = _allocate(time_left_ms)
        legal = list(board.generate_legal_moves())
        move = fallback
        stats = {"move": move.uci(), "depth": 0, "nodes": 0, "qnodes": 0}
        if len(legal) > 1 and hard > 0 and clock() < start + hard:
            search = _Search(board, _GAME, start + hard, start + soft)
            move, stats = search.run(legal)
        if move not in legal:
            move = fallback
        result = move.uci()
        _GAME.retain(board, move)
        stats.update(elapsed=clock() - start, soft_limit=soft, hard_limit=hard,
                     exception_count=_GAME.exceptions, epoch=_GAME.epoch)
        _GAME.last_stats = stats
        return result
    except Exception as exc:
        _GAME.exceptions += 1
        _GAME.last_stats = {"exception": type(exc).__name__ + ": " + str(exc),
                            "exception_count": _GAME.exceptions}
        try:
            board = chess.Board(fen)
            fallback = next(board.generate_legal_moves(), None)
            if fallback is not None:
                _GAME.observe(board)
                _GAME.retain(board, fallback)
            return fallback.uci() if fallback is not None else "0000"
        except Exception:
            return fallback.uci() if fallback is not None else "0000"
