# Stochastic Gambit

A pure-Python chess engine with a single-file competition interface, regression tests, benchmarks, and a preserved development history. The current engine is **Astra v0.3**, built for Chessathon and included in `submission/agent.py`.

The engine uses `chess` (python-chess) for board representation and legal move generation. Search, evaluation, time management, and game-history tracking live in the engine itself. It does not require an external engine, opening book, neural model, or tablebase.

## Quick start

Use **Python 3.12** (the recorded development environment used Python 3.12.14 and `chess` 1.11.2). From the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.

Call the engine from Python:

```python
import chess
from submission.agent import get_move

board = chess.Board()
move_uci = get_move(board.fen(), time_left_ms=1000)
move = chess.Move.from_uci(move_uci)
assert move in board.legal_moves
board.push(move)
print(board)
```

`get_move(fen: str, time_left_ms: int) -> str` accepts a standard-chess FEN and the remaining clock in milliseconds. It returns a UCI move such as `g1f3`, or `0000` when there are no legal moves. Move strings use UCI notation; the module is not a standalone UCI-protocol executable or a graphical chess application.

The competition time control is **120 seconds + 500 ms per move**. The allocator assumes that increment and keeps a 150 ms reserve. Pass the clock remaining before the increment is added. Keep the same engine instance throughout a game so repetition history is retained, and start a fresh Python process for each new game. Valid standard-chess FENs are expected; variants and Chess960 are outside the supported contract.

## Engine features

- Iterative deepening with alpha-beta negamax, principal variation search, and aspiration windows.
- A bounded 180,000-entry transposition table, staged move ordering, killers, and history heuristics.
- Check-aware quiescence, promotion handling, static exchange evaluation, conservative late move reductions, and guarded null-move pruning.
- Incremental tapered evaluation with formula-generated piece-square tables, pawn structure, rook files, king shelter, and endgame terms.
- Cross-call repetition tracking, fifty-move handling, and mate-distance scoring.
- Soft and hard search budgets, frequent clock checks, and a legal-move fallback.

See [the design notes](dev/DESIGN.md) for the implementation details and [the development report](dev/REPORT.md) for measurements and known limitations.

## Tests and benchmarks

Run these commands from the repository root with the virtual environment activated:

```sh
# Core legality, terminal-position, fallback, and search regression checks
python dev/tests.py --group core

# Full regression suite, including timing and endgame conversion
python dev/tests.py --group all

# Seven benchmark positions, up to 2.5 seconds per position
python dev/bench.py --seconds 2.5

# Low-clock, simulated slower-clock, and transposition-table memory checks
python dev/stress.py

# Compare the current engine against the original snapshot
python dev/match.py --opponent dev/snapshots/v0/agent.py --games 4 --seconds 0.08 --cap 120
```

Other test groups are `incremental`, `history`, `tactics`, `random`, `timing`, and `conversion`. The scripts print JSON records to standard output. Timing and benchmark results depend on the machine and system load. The stress script uses the Unix `resource` module.

The preserved v0.3 results record **48,548 assertions and 408 checked API calls**, with zero illegal moves, unexpected exceptions, or timing flags. An additional 54 stress calls also passed. These are historical local correctness measurements, not an Elo rating or a guarantee on other hardware. See [the saved results](dev/results/) for the original data.

## Repository contents

| Path | Contents |
| --- | --- |
| `submission/agent.py` | Current single-file Astra v0.3 engine |
| `dev/chessathon-submission.zip` | Competition archive containing only `agent.py` |
| `dev/tests.py` | Correctness, history, tactics, timing, and conversion checks |
| `dev/bench.py` | Benchmarks, profiling, and evaluation diagnostics |
| `dev/match.py` | Time-capped local regression games |
| `dev/stress.py` | Clock and memory stress checks |
| `dev/see_probe.py` | Static exchange evaluation checks against legal recaptures |
| `dev/snapshots/` | Preserved engine versions v0 through v0.3 |
| `dev/results/` | Saved tests, benchmarks, stress results, and package smoke test |
| `dev/DESIGN.md`, `dev/REPORT.md`, `dev/DEVLOG.md` | Architecture, results, and development chronology |
| `dev/RESUME.md` | Historical development checkpoints |
| `dev/external_strength/` | Archived external-match runner, worker, tests, and reporting tools |

The submission source matches `dev/snapshots/v0.3/agent.py` and the `agent.py` inside the ZIP. To use the competition archive, extract it and import `get_move` from `agent` with `chess` installed.

### External-match tools

The scripts in `dev/external_strength/` preserve the original Astra-versus-Build3 experiment. They contain absolute paths to the original development machine and depend on a separate competition contract, opening corpus, opponent archive, Python environment, and result directory. Those external files are **not included in this repository**, so these scripts and their tests are not runnable from a fresh clone without restoring or adapting that setup. The extension script also contains the original fixed September 11, 2026 cutoff.

The `RESUME.md` files describe historical checkpoints, including match monitoring instructions; they are not current setup instructions. External-match results are stored outside this project and are not represented by the local regression measurements above.

## Limitations

This is a compact classical engine with limited pure-Python search depth and a simple evaluation. Complex endgames, fortresses, and repetition-sensitive transpositions remain potential weaknesses. The project contains no GUI, online play service, or independently established absolute Elo rating.

The repository excludes local virtual environments, Python caches, and credentials. Install the dependency using `requirements.txt` after cloning.
