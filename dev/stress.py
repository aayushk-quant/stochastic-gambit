"""Low-clock/slow-clock and bounded-memory stress; no full games."""
import argparse
import json
import resource
import sys
import time
from pathlib import Path

import chess
from bench import ROOT, POSITIONS, load_engine


def run(path):
    engine = load_engine(path)
    original_clock = engine.clock
    records = []
    illegal = exceptions = flags = 0
    try:
        for factor in (1, 3, 6):
            engine.clock = lambda: original_clock() * factor
            for name in ("tactical", "quiet", "passed_pawns"):
                board = chess.Board(POSITIONS[name])
                for milliseconds in (120000, 1000, 300, 50, 1, 0):
                    engine._GAME = engine._Game()
                    started = time.perf_counter()
                    uci = engine.get_move(board.fen(), milliseconds)
                    elapsed = time.perf_counter() - started
                    move = chess.Move.from_uci(uci)
                    illegal += move not in board.legal_moves
                    exceptions += engine._GAME.exceptions
                    simulated_elapsed = elapsed * factor
                    if milliseconds > 1:
                        flags += simulated_elapsed > milliseconds / 1000
                    hard = engine._allocate(milliseconds)[1]
                    records.append({"factor": factor, "position": name, "clock_ms": milliseconds,
                                    "real_wall": elapsed, "scaled_wall": simulated_elapsed,
                                    "hard": hard, "scaled_overrun": max(0, simulated_elapsed - hard),
                                    "depth": engine._GAME.last_stats.get("depth", 0)})
            print(json.dumps({"factor_finished": factor, "calls": len(records),
                              "illegal": illegal, "exceptions": exceptions, "flags": flags}), flush=True)
    finally:
        engine.clock = original_clock
    assert illegal == exceptions == flags == 0
    # Fill beyond capacity with distinct, realistically sized keys and entries.
    # These artificial keys are never searched; this tests memory and eviction.
    board = chess.Board()
    game = engine._Game()
    game.observe(board)
    search = engine._Search(board, game, float("inf"), float("inf"))
    started = time.perf_counter()
    for index in range(engine.TT_LIMIT + 20000):
        key = tuple(((index + 1) * 6364136223846793005 + part * 1442695040888963407) & ((1 << 64) - 1) for part in range(8)) + (bool(index & 1), index & 15, None)
        move = chess.Move(index & 63, (index * 3 + 17) & 63)
        search.store(key, 5, index % 1000, 0, move, 0)
    assert len(game.tt) == engine.TT_LIMIT
    assert len(game.tt_order) == engine.TT_LIMIT
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    assert rss_bytes < 2_000_000_000
    result = {"calls": len(records), "illegal": illegal, "exceptions": exceptions, "flags": flags,
              "max_scaled_overrun": max(row["scaled_overrun"] for row in records),
              "tt_entries": len(game.tt), "tt_fill_seconds": time.perf_counter() - started,
              "peak_rss_bytes": rss_bytes, "records": records}
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=ROOT / "submission" / "agent.py")
    run(parser.parse_args().engine)
