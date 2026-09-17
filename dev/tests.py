"""Correctness, tactical and time-control regression tests; standard library only."""
import argparse
import importlib.util
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import chess
from bench import ROOT, POSITIONS, load_engine


class Suite:
    def __init__(self, engine):
        self.e = engine
        self.checks = self.calls = self.illegal = self.exceptions = self.flags = 0
        self.records = []

    def check(self, condition, message):
        self.checks += 1
        if not condition:
            raise AssertionError(message)

    def fresh(self):
        self.e._GAME = self.e._Game()

    def call(self, board, ms=300, label="", timing=False):
        before = self.e._GAME.exceptions
        start = time.perf_counter()
        try:
            text = self.e.get_move(board.fen(), ms)
        except Exception:
            self.exceptions += 1
            raise
        elapsed = time.perf_counter() - start
        self.calls += 1
        self.exceptions += self.e._GAME.exceptions - before
        moves = list(board.legal_moves)
        if moves:
            try:
                move = chess.Move.from_uci(text)
                legal = move in moves
            except Exception:
                legal = False
            self.illegal += not legal
            self.check(legal, f"Illegal {text} in {board.fen()}: {self.e._GAME.last_stats}")
        else:
            move = None
            self.check(text == "0000", f"Terminal should return sentinel, got {text}")
        self.check(self.e._GAME.exceptions == before, str(self.e._GAME.last_stats))
        if timing:
            hard = self.e._allocate(ms)[1]
            if ms > 1:
                self.flags += elapsed > ms / 1000
                self.check(elapsed <= ms / 1000, f"Flag: {ms}ms took {elapsed:.6f}s")
            self.records.append({"name": label, "clock_ms": ms, "wall": elapsed,
                                 "hard": hard, "overrun": max(0, elapsed - hard),
                                 "depth": self.e._GAME.last_stats.get("depth", 0)})
        return move

    def core(self):
        cases = {
            "white": chess.STARTING_FEN,
            "black": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "check": "4k3/8/8/8/8/8/4r3/4K2R w K - 0 1",
            "castle": "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            "ep": "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2",
            "promotion": "7k/P7/5K2/8/8/8/8/8 w - - 0 1",
            "underpromotion": "8/k1P5/8/2K5/8/8/8/8 w - - 0 1",
            "halfmove99": "7k/8/5KQ1/8/8/8/8/8 w - - 99 70",
            "halfmove100": "6k1/8/8/8/8/8/8/KQ6 w - - 100 70",
            "halfmove150": "6k1/8/8/8/8/8/8/KR6 w - - 150 90",
            "bare_kings": "6k1/8/8/8/8/8/8/K7 w - - 0 1",
            "minor": "6k1/8/8/8/8/8/8/KB6 w - - 0 1",
            "checkmate": "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
            "stalemate": "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1",
        }
        for label, fen in cases.items():
            self.fresh()
            board = chess.Board(fen)
            self.check(board.is_valid(), f"Invalid fixture {label}")
            self.call(board, 1000, label)
            self.fresh()
            self.call(board.mirror(), 300, label + "_mirror")
        # Fail during search deliberately: the wrapper must return and record.
        self.fresh()
        single = chess.Board("8/8/8/8/8/1k6/r7/K7 w - - 0 1")
        self.check(len(list(single.legal_moves)) == 1, "single move fixture")
        self.call(single, 120000, "single_move", True)
        self.check(self.e._GAME.last_stats["depth"] == 0, "single move searched")
        self.fresh()
        original = self.e._Search.run
        def broken(*args):
            raise RuntimeError("injected search failure")
        self.e._Search.run = broken
        board = chess.Board()
        try:
            move = chess.Move.from_uci(self.e.get_move(board.fen(), 1000))
            self.check(move in board.legal_moves, "fallback illegal")
            board.push(move)
            self.check(self.e._GAME.seen[-1] == self.e._key(board), "fallback not recorded")
            self.check(self.e._GAME.exceptions == 1, "injection not observed")
        finally:
            self.e._Search.run = original
        self.fresh()
        # TT mate score adjustment must survive different root distances.
        b = chess.Board()
        game = self.e._Game()
        game.observe(b)
        search = self.e._Search(b, game, time.perf_counter() + 20, time.perf_counter() + 20)
        key = self.e._key(b)
        search.store(key, 8, self.e.MATE - 7, 0, next(iter(b.legal_moves)), 3)
        self.check(game.tt[key][1] == self.e.MATE - 4, "positive TT mate adjustment")
        search.store(key, 8, -self.e.MATE + 9, 0, next(iter(b.legal_moves)), 5)
        self.check(game.tt[key][1] == -self.e.MATE + 4, "negative TT mate adjustment")
        self.check(search.search(1, -1, 0, 7) == -self.e.MATE + 11, "TT negative mate retrieval")
        search.store(key, 8, self.e.MATE - 7, 0, next(iter(b.legal_moves)), 3)
        self.check(search.search(1, 0, 1, 7) == self.e.MATE - 11, "TT positive mate retrieval")
        # A non-pawn piece can be immobilized in stalemate; null pruning must
        # not turn that terminal node into a non-draw score.
        b = chess.Board("r6k/8/8/8/8/8/N1q5/K7 w - - 0 1")
        self.check(b.is_valid() and b.is_stalemate(), "pinned-piece stalemate fixture")
        game = self.e._Game()
        game.observe(b)
        search = self.e._Search(b, game, time.perf_counter() + 2, time.perf_counter() + 2)
        self.check(search.search(4, -3001, -3000, 1) == search.draw_score(), "stalemate lost to null pruning")
        self.check(search.qsearch(-self.e.INF, self.e.INF, self.e.MAX_PLY) == search.draw_score(), "stalemate lost at maximum ply")
        for fen, is_mate in (("7k/6Q1/5K2/8/8/8/8/8 b - - 100 80", True),
                             ("7k/8/8/8/8/8/8/KQ6 w - - 100 80", False)):
            limit_board = chess.Board(fen)
            limit_game = self.e._Game()
            limit_game.observe(limit_board)
            limit_search = self.e._Search(limit_board, limit_game, time.perf_counter() + 2, time.perf_counter() + 2)
            expected = -self.e.MATE + self.e.MAX_PLY if is_mate else limit_search.draw_score()
            self.check(limit_search.qsearch(-self.e.INF, self.e.INF, self.e.MAX_PLY) == expected, "draw/mate precedence lost at maximum ply")
        limit_board.halfmove_clock = 5
        limit_search = self.e._Search(limit_board, limit_game, time.perf_counter() + 2, time.perf_counter() + 2)
        limit_search.prior[self.e._key(limit_board)] = 2
        self.check(limit_search.qsearch(-self.e.INF, self.e.INF, self.e.MAX_PLY) == limit_search.draw_score(), "repetition lost at maximum ply")
        # A high search bound can prune late quiet moves, but cannot turn a
        # nonterminal position into a stalemate result.
        live = chess.Board()
        live_game = self.e._Game()
        live_game.observe(live)
        live_search = self.e._Search(live, live_game, time.perf_counter() + 2, time.perf_counter() + 2)
        live_search.evaluate = lambda: 321 if live.turn else -321
        self.check(live_search.search(1, 5000, 5001, 1) == 321, "quiet pruning produced false terminal score")
        # Private API fallback must match its documented counter-free identity.
        class PublicOnlyBoard(chess.Board):
            _transposition_key = None
        for fen in (chess.STARTING_FEN, "4k3/8/8/3pP3/8/8/8/4K3 w - d6 9 22"):
            self.check(self.e._key(PublicOnlyBoard(fen)) == self.e._key(chess.Board(fen)), "public key fallback mismatch")
        previous_limit = self.e.TT_LIMIT
        self.e.TT_LIMIT = 64
        try:
            for i in range(300):
                search.store((i,), 4, i, 0, None, 1)
                self.check(len(game.tt) <= 64, "TT cap exceeded")
            if hasattr(game, "tt_order"):
                self.check(len(game.tt_order) == len(game.tt), "TT eviction queue leak")
        finally:
            self.e.TT_LIMIT = previous_limit

    def incremental(self):
        rng = random.Random(917)
        checks = 0
        boards = [chess.Board(f) for f in POSITIONS.values()]
        boards += [chess.Board("r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1"),
                   chess.Board("7k/P7/8/8/8/8/1p6/7K w - - 0 1")]
        for b in boards:
            game = self.e._Game()
            game.observe(b)
            search = self.e._Search(b, game, time.perf_counter() + 20, time.perf_counter() + 20)
            for _ in range(70):
                moves = list(b.legal_moves)
                if not moves:
                    break
                if hasattr(search, "ordered_moves"):
                    ordered = list(search.ordered_moves(rng.choice(moves), 0, b.is_check()))
                    self.check(len(ordered) == len(moves) and set(ordered) == set(moves), "staged generator missing or duplicating legal moves")
                parent = search.mg, search.eg, search.phase
                before = b.fen()
                for move in moves:
                    search.play(move)
                    if hasattr(self.e, "_has_legal_move") and not b.is_check():
                        self.check(self.e._has_legal_move(b) == any(b.legal_moves), "legal-move existence proof failed")
                    self.check((search.mg, search.eg, search.phase) == self.e._base_eval(b), f"incremental mismatch {move} {before}")
                    b.pop()
                    search.mg, search.eg, search.phase = parent
                    self.check(b.fen() == before, "push/pop corrupt")
                    checks += 1
                move = rng.choice(moves)
                search.play(move)
        self.records.append({"incremental_moves": checks})

    def history(self):
        # Rights loss on a retry must be compared with the supplied pre-move
        # board, not the result retained from the preceding attempted call.
        castle_fen = "r3k2r/8/8/8/8/8/8/R3K1NR w KQkq - 0 1"
        for retry_move, expected_size in (("h1h2", 1), ("g1f3", 2)):
            rights_game = self.e._Game()
            rights_board = chess.Board(castle_fen)
            rights_game.observe(rights_board)
            rights_game.retain(rights_board, chess.Move.from_uci("h1h2"))
            self.check(len(rights_game.seen) == 1, "own castling-rights loss not irreversible")
            retry_board = chess.Board(castle_fen)
            self.check(rights_game.observe(retry_board) == "retry", "rights retry not recognized")
            rights_game.retain(retry_board, chess.Move.from_uci(retry_move))
            self.check(len(rights_game.seen) == expected_size, "retry castling-rights history corrupted")
        rights_game = self.e._Game()
        rights_board = chess.Board(castle_fen)
        rights_game.observe(rights_board)
        rights_game.retain(rights_board, chess.Move.from_uci("g1f3"))
        rights_board.push_uci("a8a7")
        rights_game.observe(rights_board)
        self.check(rights_game.seen == [self.e._key(rights_board)], "opponent rights loss did not clear history")
        self.fresh()
        b = chess.Board()
        move = self.call(b, 0)
        seen = self.e._GAME.seen[:]
        altered = chess.Board(b.fen())
        altered.fullmove_number = 50
        altered.halfmove_clock = 71
        retry = self.call(altered, 0)
        self.check(move == retry, "retry changed fallback")
        self.check(self.e._GAME.seen == seen, "retry duplicated history")
        b.push(move)
        opponent = chess.Move.from_uci("e7e5")
        self.check(opponent in b.legal_moves, "opponent fixture")
        b.push(opponent)
        fen_with_ep = b.fen(en_passant="fen")
        canonical = b.fen(en_passant="legal")
        self.check(fen_with_ep != canonical, "EP fixture must differ")
        self.check(self.e._key(chess.Board(fen_with_ep)) == self.e._key(chess.Board(canonical)), "irrelevant EP affects identity")
        self.call(b, 0)
        seen = self.e._GAME.seen[:]
        self.e.get_move(fen_with_ep, 0)
        self.check(self.e._GAME.seen == seen, "EP retry duplicated history")
        # Feed a real reversible sequence through observe/retain to test both
        # our returned positions and supplied opponent positions.
        game = self.e._Game()
        b = chess.Board("6nk/8/8/8/8/8/8/KQ4N1 w - - 0 1")
        start_key = self.e._key(b)
        for our, theirs in (("g1f3", "g8f6"), ("f3g1", "f6g8")):
            game.observe(b)
            ours = chess.Move.from_uci(our)
            self.check(ours in b.legal_moves, "history own move")
            retained = chess.Board(b.fen())
            game.retain(retained, ours)
            b.push(ours)
            b.push_uci(theirs)
        game.observe(b)
        self.check(game.root_history.count(start_key) == 2, "actual history lost start")
        search = self.e._Search(b, game, time.perf_counter() + 2, time.perf_counter() + 1)
        self.check(not search.repeated(start_key), "second occurrence called a draw")
        search.path.append(start_key)
        self.check(search.repeated(start_key), "third occurrence missed")
        search.path.pop()
        self.check(search.contempt < 0, "winning repetition must be discouraged")
        # A move whose result already occurred must be avoided when ahead.
        root = chess.Board("7k/8/8/8/8/8/8/KQ6 w - - 10 10")
        game = self.e._Game()
        repeatmove = chess.Move.from_uci("b1b8")
        root.push(repeatmove)
        repeated_key = self.e._key(root)
        root.pop()
        game.seen = [repeated_key, repeated_key]
        game.observe(root)
        search = self.e._Search(root, game, time.perf_counter() + 0.6, time.perf_counter() + 0.5)
        chosen, stats = search.run(list(root.legal_moves))
        self.check(chosen != repeatmove, "selected winning repetition")
        self.records.append({"winning_repetition_move": chosen.uci(), "score": stats["score"]})
        # End-to-end API history: reach a twice-seen resulting position from
        # a new predecessor, so the root itself has not already drawn.
        self.fresh()
        b = chess.Board("6nk/8/8/8/8/8/8/KQ4N1 w - - 0 1")
        initial_fen, initial_key = b.fen(), self.e._key(b)
        plan = iter(("g1f3", "f3g1", "g1f3", "f3h2"))
        original_run = self.e._Search.run
        def scripted(search, legal):
            move = chess.Move.from_uci(next(plan))
            assert move in legal
            return move, {"move": move.uci(), "depth": 0, "nodes": 0, "qnodes": 0}
        self.e._Search.run = scripted
        target_key = None
        try:
            for index, opponent in enumerate(("g8f6", "f6g8", "g8f6", "f6g8")):
                move = self.call(b, 1000, "cross_call_setup")
                b.push(move)
                if index == 0:
                    target_key = self.e._key(b)
                b.push_uci(opponent)
                if index == 1:
                    self.check(self.e._key(b) == initial_key, "recurrence key differs")
                    self.check(b.fen() != initial_fen, "recurrence counters did not change")
                    self.check(b.halfmove_clock == 4 and b.fullmove_number == 3, "recurrence counters fixture")
        finally:
            self.e._Search.run = original_run
        self.check(self.e._GAME.seen.count(target_key) == 2, "cross-call target count incorrect")
        move = self.call(b, 20000, "cross_call_avoidance")
        self.check(move != chess.Move.from_uci("h2f3"), f"API selected third occurrence: {move}")
        self.records.append({"cross_call_repetition_avoided": True, "prior_occurrences": 2,
                             "move": move.uci(), "rejected": "h2f3",
                             "recurrence_counters": [[0, 1], [4, 3]]})

    def tactics(self):
        # Exhaustive legal search independently proves these small fixtures.
        cases = [("mate1", "7k/8/5KQ1/8/8/8/8/8 w - - 0 1", 1),
                 ("mate2", "7k/8/8/5K2/6Q1/8/8/8 w - - 0 1", 3)]
        for name, fen, plies in cases:
            b = chess.Board(fen)
            wins = winning_mates(b, plies)
            self.check(bool(wins), f"{name} fixture has no proved mate")
            if plies == 3:
                self.check(not winning_mates(b, 1), "mate2 fixture also has mate1")
            for board in (b, b.mirror()):
                self.fresh()
                wins = winning_mates(board, plies)
                move = self.call(board, 20000, name)
                self.check(move in wins, f"{name} missed: {move}; winning {wins}")
                self.records.append({"tactic": name, "move": move.uci(), "depth": self.e._GAME.last_stats.get("depth")})
        self.fresh()
        b = chess.Board("8/k1P5/8/2K5/8/8/8/8 w - - 0 1")
        q = chess.Move.from_uci("c7c8q")
        b.push(q)
        self.check(not b.is_check() and not any(b.legal_moves), "underpromotion fixture not stalemate")
        b.pop()
        move = self.call(b, 60000, "underpromotion")
        self.check(move != q, f"stalemating queen promotion selected: {move}")
        game = self.e._Game()
        game.observe(b)
        search = self.e._Search(b, game, time.perf_counter() + 2, time.perf_counter() + 1)
        score = search.qsearch(-self.e.INF, self.e.INF, 0)
        self.check(score > 500, f"quiet rook underpromotion absent from qsearch: {score}")
        self.records.append({"tactic": "underpromotion", "move": move.uci(), "qscore": score})
        self.fresh()
        b = chess.Board("8/5P1k/4KB2/6Q1/8/8/8/8 w - - 0 1")
        self.check(b.is_valid(), "knight promotion fixture invalid")
        move = self.call(b, 1000, "knight_underpromotion")
        self.check(move == chess.Move.from_uci("f7f8n"), f"knight underpromotion missed: {move}")
        b.push(move)
        self.check(b.is_checkmate(), "knight underpromotion not mate")
        self.records.append({"tactic": "knight_underpromotion", "move": move.uci()})
        forcing = (
            ("back_rank_mate", "6k1/3r1ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1", "e1e8"),
            ("smothered_mate", "6rk/6pp/8/6N1/8/8/8/K7 w - - 0 1", "g5f7"),
            ("queen_capture", "r4rk1/ppp2ppp/2n5/2bqp3/8/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 12", "c3d5"),
            ("knight_fork", "5q2/p5kp/8/8/3N4/8/P6P/R5K1 w - - 0 1", "d4e6"),
            ("rook_skewer", "4q3/4k3/8/8/8/8/8/R5KR w - - 0 1", "a1e1"),
        )
        for label, fen, expected in forcing:
            self.fresh()
            board = chess.Board(fen)
            self.check(board.is_valid(), f"invalid forcing fixture {label}")
            move = self.call(board, 10000, label)
            self.check(move.uci() == expected, f"{label} missed: {move}, expected {expected}")
            self.records.append({"tactic": label, "move": move.uci(), "depth": self.e._GAME.last_stats["depth"]})
        self.fresh()
        b = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 99 70")
        move = self.call(b, 10000)
        b.push(move)
        self.check(b.is_checkmate(), "fifty-move draw incorrectly precedes mate")

    def random(self, count=350):
        rng = random.Random(20260910)
        b = chess.Board()
        self.fresh()
        for i in range(count):
            if b.is_game_over() or i % 80 == 0:
                b = chess.Board()
                self.fresh()
            for _ in range(rng.randrange(1, 5)):
                moves = list(b.legal_moves)
                if not moves:
                    break
                b.push(rng.choice(moves))
            if not any(b.legal_moves):
                continue
            self.call(b, (0, 50, 300, 1000)[i % 4], "random")
        self.records.append({"random_positions_requested": count})

    def timing(self):
        engine_path = str(Path(self.e.__file__).resolve())
        code = ("import time, importlib.util, json; start=time.perf_counter(); import chess; "
                f"spec=importlib.util.spec_from_file_location('fresh_agent', {engine_path!r}); "
                "agent=importlib.util.module_from_spec(spec); spec.loader.exec_module(agent); "
                "init=time.perf_counter()-start; "
                f"board=chess.Board({POSITIONS['quiet']!r}); start=time.perf_counter(); "
                "move=agent.get_move(board.fen(), 120000); elapsed=time.perf_counter()-start; "
                "assert chess.Move.from_uci(move) in board.legal_moves; "
                "hard=agent._GAME.last_stats['hard_limit']; "
                "print(json.dumps({'name':'first_call_after_import','clock_ms':120000,"
                "'wall':elapsed,'hard':hard,'overrun':max(0,elapsed-hard),'import_seconds':init}))")
        fresh = subprocess.run([sys.executable, "-B", "-c", code], cwd="/private/tmp", capture_output=True, text=True, check=True)
        first = json.loads(fresh.stdout)
        self.check(first["wall"] < 120.0 and first["import_seconds"] < 90, "first-call/init budget")
        self.records.append(first)
        for ms in (120000, 60000, 30000, 10000, 5000, 1000, 300, 50, 1, 0):
            self.fresh()
            self.call(chess.Board(POSITIONS["quiet"]), ms, "real_call", True)
        maximum = max(record["overrun"] for record in self.records if "overrun" in record)
        self.records.append({"maximum_hard_limit_overrun_seconds": maximum,
                             "includes_first_call_after_import": True})
        measured_overhead = 0
        b = chess.Board()
        for _ in range(100):
            self.fresh()
            start = time.perf_counter()
            self.e.get_move(b.fen(), 0)
            measured_overhead = max(measured_overhead, time.perf_counter() - start)
        # Allow for slower target hardware and periodic deadline-check overshoot.
        charged_overhead = max(0.020, measured_overhead * 6)
        for initial in (120.0, 60.0, 10.0, 1.0, 0.3):
            remaining = initial
            minimum = remaining
            for _ in range(300):
                soft, hard = self.e._allocate(remaining * 1000)
                self.check(0 <= soft <= hard, "allocator limits inverted")
                remaining -= hard + charged_overhead
                minimum = min(minimum, remaining)
                self.check(remaining >= 0.150, f"clock below reserve: {initial}, {remaining}")
                remaining += 0.5
            self.records.append({"simulation_initial": initial, "final": remaining,
                                 "minimum_before_increment": minimum, "charged_overhead": charged_overhead})

    def conversion(self, seconds=0.7, wall_cap=160):
        deadline = time.perf_counter() + wall_cap
        for name, fen in (("KQ", "8/8/3k4/8/8/1K6/8/7Q w - - 0 1"),
                          ("KR", "8/8/3k4/8/8/1K6/8/7R w - - 0 1")):
            b = chess.Board(fen)
            games = [self.e._Game(), self.e._Game()]
            start = time.perf_counter()
            for ply in range(100):
                self.check(time.perf_counter() < deadline, "conversion wall cap exceeded")
                if b.is_game_over(claim_draw=True):
                    break
                game = games[b.turn]
                game.observe(b)
                moment = time.perf_counter()
                search = self.e._Search(b, game, moment + seconds, moment + seconds * 0.7)
                move, stats = search.run(list(b.legal_moves))
                self.check(move in b.legal_moves, "conversion illegal")
                retained = chess.Board(b.fen())
                game.retain(retained, move)
                b.push(move)
            self.records.append({"conversion": name, "plies": b.ply(), "halfmove": b.halfmove_clock,
                                 "outcome": b.result(claim_draw=True), "wall": time.perf_counter() - start,
                                 "fen": b.fen()})
            print(json.dumps(self.records[-1]), flush=True)
            self.check(b.is_checkmate(), f"{name} not mated: {b.fen()}")

    def report(self):
        return {"checks": self.checks, "calls": self.calls, "illegal": self.illegal,
                "exceptions": self.exceptions, "flags": self.flags, "records": self.records}


def forced_mate(board, plies, attacker):
    moves = list(board.legal_moves)
    if not moves:
        return board.is_check() and board.turn != attacker
    if plies <= 0:
        return False
    attacking = board.turn == attacker
    for move in moves:
        board.push(move)
        result = forced_mate(board, plies - 1, attacker)
        board.pop()
        if result == attacking:
            return attacking
    return not attacking


def winning_mates(board, plies):
    attacker = board.turn
    wins = []
    for move in list(board.legal_moves):
        board.push(move)
        if forced_mate(board, plies - 1, attacker):
            wins.append(move)
        board.pop()
    return wins


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("core", "incremental", "history", "tactics", "random", "timing", "conversion", "all"), default="all")
    parser.add_argument("--engine", type=Path, default=ROOT / "submission" / "agent.py")
    args = parser.parse_args()
    suite = Suite(load_engine(args.engine))
    groups = ("core", "incremental", "history", "tactics", "random", "timing", "conversion") if args.group == "all" else (args.group,)
    start = time.perf_counter()
    try:
        for group in groups:
            getattr(suite, group)()
            print(json.dumps({"passed": group, "elapsed": time.perf_counter() - start,
                              "checks": suite.checks, "calls": suite.calls}), flush=True)
    finally:
        print(json.dumps(suite.report()), flush=True)
