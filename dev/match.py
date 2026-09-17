"""Wall-capped regression games, never used as evidence of Elo improvement."""
import argparse
import json
import random
import time
from pathlib import Path
import chess
from bench import ROOT, load_engine


OPENINGS = (
    ("e2e4", "e7e5", "g1f3", "b8c6"),
    ("d2d4", "d7d5", "c2c4", "e7e6"),
    ("e2e4", "c7c5", "g1f3", "d7d6"),
    ("g1f3", "d7d5", "g2g3", "g8f6"),
)


def run(candidate, opponent=None, cap=240, games=4, seconds=0.08):
    rng = random.Random(42)
    started = time.perf_counter()
    deadline = started + min(300, cap)
    results = []
    for number in range(games):
        if time.perf_counter() >= deadline:
            break
        a = load_engine(candidate)
        b = load_engine(opponent) if opponent else None
        players = [a, b] if number % 2 else [b, a]
        board = chess.Board()
        for move in OPENINGS[(number // 2) % len(OPENINGS)]:
            board.push_uci(move)
        initial = 1.2
        increment = 0.005
        clocks = [initial, initial]
        reason = "ply_cap"
        max_call = 0.0
        illegal = flags = exceptions = 0
        for ply in range(600 - board.ply()):
            if board.is_game_over(claim_draw=True):
                reason = "normal"
                break
            if time.perf_counter() >= deadline:
                reason = "wall_cap"
                break
            color = board.turn
            player = players[color]
            before = time.perf_counter()
            if player is None:
                move = rng.choice(list(board.legal_moves))
            elif opponent:
                player._GAME.observe(board)
                hard = min(seconds, max(0.001, deadline - before))
                search = player._Search(board, player._GAME, before + hard, before + hard * 0.7)
                move, _ = search.run(list(board.legal_moves))
                retained = chess.Board(board.fen())
                player._GAME.retain(retained, move)
            else:
                move = chess.Move.from_uci(player.get_move(board.fen(), int(clocks[color] * 1000)))
                exceptions += player._GAME.last_stats.get("exception_count", 0)
            elapsed = time.perf_counter() - before
            max_call = max(max_call, elapsed)
            if not opponent and player is not None:
                clocks[color] -= elapsed
                if clocks[color] < 0:
                    flags += 1
                    reason = "flag"
                    break
                clocks[color] += increment
            if move not in board.legal_moves:
                illegal += 1
                reason = "illegal"
                break
            board.push(move)
        record = {"game": number, "candidate_white": number % 2 == 0,
                  "result": board.result(claim_draw=True), "reason": reason,
                  "plies": board.ply(), "illegal": illegal, "flags": flags,
                  "exceptions": exceptions, "max_call": max_call,
                  "clocks": clocks, "fen": board.fen()}
        results.append(record)
        print(json.dumps(record), flush=True)
        if reason == "wall_cap":
            break
    print(json.dumps({"wall": time.perf_counter() - started, "games": len(results),
                      "results": results}), flush=True)
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=Path, default=ROOT / "submission" / "agent.py")
    p.add_argument("--opponent", type=Path)
    p.add_argument("--cap", type=float, default=120)
    p.add_argument("--games", type=int, default=4)
    p.add_argument("--seconds", type=float, default=0.08)
    args = p.parse_args()
    run(args.candidate, args.opponent, args.cap, args.games, args.seconds)
