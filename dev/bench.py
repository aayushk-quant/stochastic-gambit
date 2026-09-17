"""Clean-sheet benchmark positions and diagnostics; no external engines."""
import argparse
import importlib.util
import json
import sys
import time
import cProfile
import pstats
import inspect
import textwrap
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
POSITIONS = {
    "opening": chess.STARTING_FEN,
    "tactical": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "quiet": "r2q1rk1/pp2bppp/2npbn2/2p1p3/4P3/2PP1N1P/PPBN1PP1/R1BQR1K1 w - - 0 10",
    "endgame": "8/2p2k2/1p1p1p2/p2Pp3/P1P1P1P1/1P3K2/8/8 w - - 0 40",
    "imbalance": "2r3k1/pp3ppp/4p3/3q4/3P4/2P1BN2/PP3PPP/3RR1K1 w - - 0 25",
    "king_safety": "r4rk1/ppp2ppp/2nq4/2b1p3/8/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 12",
    "passed_pawns": "8/5pk1/7p/2P5/3K4/8/5PPP/8 w - - 0 40",
}


def load_engine(path=ROOT / "submission" / "agent.py"):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("bench_agent", path)
    mod = importlib.util.module_from_spec(spec)
    start = time.perf_counter()
    spec.loader.exec_module(mod)
    mod._import_seconds = time.perf_counter() - start
    return mod


def micro():
    boards = [chess.Board(fen) for fen in POSITIONS.values()]
    total = 0
    start = time.perf_counter()
    for _ in range(400):
        for board in boards:
            for move in board.generate_legal_moves():
                board.push(move)
                board._transposition_key()
                total += 1
                board.pop()
    elapsed = time.perf_counter() - start
    print(json.dumps({"test": "legal_push_key_pop", "nodes": total,
                      "seconds": elapsed, "nps": int(total / elapsed)}), flush=True)
    board = boards[1]
    moves = list(board.legal_moves)
    count = 100000
    start = time.perf_counter()
    for i in range(count):
        board.push(moves[i % len(moves)])
        board.pop()
    elapsed = time.perf_counter() - start
    print(json.dumps({"test": "push_pop", "nodes": count, "seconds": elapsed,
                      "nps": int(count / elapsed)}), flush=True)
    start = time.perf_counter()
    score = 0
    for i in range(count):
        b = boards[i % len(boards)]
        for color in (chess.WHITE, chess.BLACK):
            occ = b.occupied_co[color]
            score += (b.pawns & occ).bit_count() * 100
            score += (b.knights & occ).bit_count() * 320
            score += (b.bishops & occ).bit_count() * 330
            score += (b.rooks & occ).bit_count() * 500
            score += (b.queens & occ).bit_count() * 950
    elapsed = time.perf_counter() - start
    print(json.dumps({"test": "material_bitboards", "evaluations": count,
                      "seconds": elapsed, "evals_per_second": int(count / elapsed),
                      "checksum": score}), flush=True)


def analyse(engine, fen, seconds=2.5):
    board = chess.Board(fen)
    game = engine._Game()
    game.observe(board)
    legal = list(board.generate_legal_moves())
    if not legal:
        return {"move": "0000", "depth": 0}
    start = time.perf_counter()
    search = engine._Search(board, game, start + seconds, start + seconds * 0.90)
    _, stats = search.run(legal)
    return stats


def run(seconds, path):
    engine = load_engine(path)
    print(json.dumps({"import_seconds": engine._import_seconds}), flush=True)
    for name, fen in POSITIONS.items():
        start = time.perf_counter()
        result = analyse(engine, fen, seconds)
        result = dict(result)
        result.update(name=name, fen=fen, wall=time.perf_counter() - start)
        print(json.dumps(result), flush=True)


def fixed_depth(depth, path, profile=False):
    engine = load_engine(path)
    profiler = cProfile.Profile()
    if profile:
        profiler.enable()
    for name, fen in POSITIONS.items():
        board = chess.Board(fen)
        game = engine._Game()
        game.observe(board)
        start = time.perf_counter()
        search = engine._Search(board, game, start + 45, start + 45)
        value = 0
        for d in range(1, depth + 1):
            value = search.search(d, -engine.INF, engine.INF, 0)
        elapsed = time.perf_counter() - start
        print(json.dumps({"name": name, "depth": depth, "wall": elapsed,
                          "nodes": search.nodes, "qnodes": search.qnodes,
                          "nps": int((search.nodes + search.qnodes) / elapsed),
                          "score": value, "move": search.partial_move.uci()}), flush=True)
    if profile:
        profiler.disable()
        pstats.Stats(profiler).strip_dirs().sort_stats("cumtime").print_stats(35)


def compare_evaluation(path, reference):
    candidate, baseline = load_engine(path), load_engine(reference)
    rng = __import__("random").Random(73)
    checked = 0
    for fen in POSITIONS.values():
        board = chess.Board(fen)
        for _ in range(100):
            left = candidate._Search(board, candidate._Game(), float("inf"), float("inf"))
            right = baseline._Search(board, baseline._Game(), float("inf"), float("inf"))
            assert left.evaluate() == right.evaluate(), (board.fen(), left.evaluate(), right.evaluate())
            checked += 1
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
    print(json.dumps({"identical_evaluations": checked}), flush=True)
    for name, engine in (("reference", baseline), ("candidate", candidate)):
        searches = [engine._Search(chess.Board(fen), engine._Game(), float("inf"), float("inf")) for fen in POSITIONS.values()]
        start = time.perf_counter()
        checksum = 0
        for i in range(70000):
            checksum += searches[i % len(searches)].evaluate()
        elapsed = time.perf_counter() - start
        print(json.dumps({"engine": name, "evals_per_second": int(70000 / elapsed), "checksum": checksum}), flush=True)


def ablate(path):
    """Remove one original evaluation term in memory and measure its cost."""
    engine = load_engine(path)
    original = textwrap.dedent(inspect.getsource(engine._Search.evaluate))
    variants = {"all_terms": original,
                "no_bishop_pair": original.replace("if bishops & (bishops - 1):", "if False:"),
                "no_rook_files": original.replace("for sq in scan(b.rooks & occ):", "for sq in ():"),
                "no_shelter": original.replace("if phase > 10:", "if False:"),
                "no_mopup": original.replace("if not pawns and phase <= 8:", "if False:")}
    start = original.index("    pawnkey =")
    end = original.index("    for color, occ, own, enemy, sign")
    variants["no_pawn_structure"] = original[:start] + original[end:]
    for name, source in variants.items():
        scope = dict(engine.__dict__)
        exec(compile(source, "<own-evaluator-ablation>", "exec"), scope)
        engine._Search.evaluate = scope["evaluate"]
        searches = [engine._Search(chess.Board(fen), engine._Game(), float("inf"), float("inf")) for fen in POSITIONS.values()]
        begin = time.perf_counter()
        checksum = 0
        for i in range(70000):
            checksum += searches[i % len(searches)].evaluate()
        eval_rate = int(70000 / (time.perf_counter() - begin))
        nodes = 0
        begin = time.perf_counter()
        for fen in POSITIONS.values():
            board = chess.Board(fen)
            game = engine._Game()
            game.observe(board)
            search = engine._Search(board, game, float("inf"), float("inf"))
            for depth in range(1, 5):
                search.search(depth, -engine.INF, engine.INF, 0)
            nodes += search.nodes + search.qnodes
        elapsed = time.perf_counter() - begin
        print(json.dumps({"ablation": name, "evals_per_second": eval_rate,
                          "search_nps": int(nodes / elapsed), "nodes": nodes,
                          "seconds": elapsed, "checksum": checksum}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--micro", action="store_true")
    p.add_argument("--seconds", type=float, default=2.5)
    p.add_argument("--engine", type=Path, default=ROOT / "submission" / "agent.py")
    p.add_argument("--depth", type=int)
    p.add_argument("--profile", action="store_true")
    p.add_argument("--compare-eval", type=Path)
    p.add_argument("--ablate", action="store_true")
    args = p.parse_args()
    if args.micro:
        micro()
    elif args.compare_eval:
        compare_evaluation(args.engine, args.compare_eval)
    elif args.ablate:
        ablate(args.engine)
    elif args.depth:
        fixed_depth(args.depth, args.engine, args.profile)
    else:
        run(args.seconds, args.engine)
