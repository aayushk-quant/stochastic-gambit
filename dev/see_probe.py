"""Independent checks for the original static-exchange implementation."""
import json
import random
import time
import argparse
from pathlib import Path
import chess

VALUES = (0, 100, 320, 335, 510, 975, 20000)
BB = chess.BB_SQUARES


def see(board, move):
    """Material result of an optional sequence of captures on one square."""
    target = move.to_square
    target_bit = BB[target]
    moving = board.piece_type_at(move.from_square)
    victim = board.piece_type_at(target)
    occupied = board.occupied ^ BB[move.from_square]
    if victim is None:
        if board.is_en_passant(move):
            victim = chess.PAWN
            occupied ^= BB[target - 8 if board.turn else target + 8]
        else:
            victim = 0
    gains = [VALUES[victim] + (VALUES[move.promotion] - 100 if move.promotion else 0)]
    if moving == chess.KING:
        return gains[0]
    current_value = VALUES[move.promotion or moving]
    side = not board.turn
    pieces = (0, board.pawns, board.knights, board.bishops, board.rooks, board.queens, board.kings)
    while True:
        attackers = board.attackers_mask(side, target, occupied) & board.occupied_co[side] & occupied & ~target_bit
        if not attackers:
            break
        chosen = 0
        enemy = board.occupied_co[not side] & occupied & ~target_bit
        for piece in range(1, 7):
            candidates = attackers & pieces[piece]
            while candidates:
                bit = candidates & -candidates
                candidates ^= bit
                king = target if piece == chess.KING else board.king(side)
                # Exclude pinned recaptures using the hypothetical occupancy.
                if not board.attackers_mask(not side, king, occupied ^ bit) & enemy:
                    chosen = bit
                    break
            if chosen:
                break
        if not chosen:
            break
        promotion = piece == chess.PAWN and target >> 3 in (0, 7)
        gains.append(current_value - gains[-1] + (875 if promotion else 0))
        current_value = VALUES[chess.QUEEN if promotion else piece]
        occupied ^= chosen
        side = not side
        if piece == chess.KING:
            break
    for index in range(len(gains) - 1, 0, -1):
        gains[index - 1] = min(gains[index - 1], -gains[index])
    return gains[0]


def recaptures(board, target):
    best = 0
    for move in list(board.generate_legal_captures(to_mask=BB[target])):
        victim = board.piece_type_at(target) or chess.PAWN
        gain = VALUES[victim] + (VALUES[move.promotion] - 100 if move.promotion else 0)
        board.push(move)
        value = gain - recaptures(board, target)
        board.pop()
        best = max(best, value)
    return best


def brute(board, move):
    victim = board.piece_type_at(move.to_square) or (chess.PAWN if board.is_en_passant(move) else 0)
    gain = VALUES[victim] + (VALUES[move.promotion] - 100 if move.promotion else 0)
    board.push(move)
    value = gain - recaptures(board, move.to_square)
    board.pop()
    return value


def run(positions=2000, evaluator=see):
    rng = random.Random(882)
    b = chess.Board()
    checked = false_negative = differences = 0
    examples = []
    start = time.perf_counter()
    for index in range(positions):
        if index % 100 == 0 or not any(b.legal_moves):
            b = chess.Board()
        for move in list(b.generate_legal_captures()):
            estimated = evaluator(b, move)
            exact = brute(b, move)
            checked += 1
            differences += estimated != exact
            if estimated < -60 and exact >= 0:
                false_negative += 1
                if len(examples) < 8:
                    examples.append({"fen": b.fen(), "move": move.uci(), "see": estimated, "brute": exact})
        moves = list(b.legal_moves)
        if moves:
            b.push(rng.choice(moves))
    print(json.dumps({"captures": checked, "differences": differences,
                      "unsafe_prunes": false_negative, "examples": examples,
                      "seconds": time.perf_counter() - start}), flush=True)
    assert false_negative == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=int, default=2000)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--threshold", type=int)
    args = parser.parse_args()
    if args.engine:
        from bench import load_engine
        engine = load_engine(args.engine)
        run(args.positions, lambda b, m: engine._see(b, m, args.threshold))
    else:
        run(args.positions)
