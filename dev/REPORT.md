# V0_READY_FOR_STRENGTH_TEST

Final candidate: V0.3. The submission source is frozen and matches its passing
snapshot. V0 and V0.1 remain untouched. Both interruption audits found intact
files; the last interrupted benchmark completed and its results were recovered.

Sprint start: 2026-09-10 21:42:33 BST. Original hard deadline: 23:42:33 BST.
The engine is ready before the deadline; no external strength match has run.

## 1. Architecture and provenance

One readable, independently written Python file uses python-chess legal move
generation and Board.push/pop. Incremental tapered evaluation keeps per-node
work small. The representation decision was committed about five minutes into
the sprint, after a microbenchmark measured 237,522 legal-generation/push/key/pop
operations per second.

No third-party engine, port, translation, engine source, binary, model, book or
tablebase was used. Piece-square tables use original formulas, documented in
source. General chess-programming algorithms and conventional material values
are the only inherited ideas. All static tables are generated at import.

The judges' walkthrough is [DESIGN.md](DESIGN.md), and the development chronology
is [DEVLOG.md](DEVLOG.md).

## 2. Submission files and size

The submission directory and ZIP root contain exactly one file:

| Runtime file | Uncompressed bytes |
| --- | ---: |
| agent.py | 32,210 |

The ZIP is **8,259 bytes**: [chessathon-submission.zip](chessathon-submission.zip).
No development files, logs or Python caches are included. Runtime code performs
no file access and does not depend on the working directory.

Source SHA-256:

```text
7a862a0c104ac76b5d2e7174f9cc31f7bdfe592a12c4dc125ca8b51ac470e279
```

ZIP SHA-256:

```text
3f3f7cba8798a90d69a59e3e5ca7525b5dcf6c8ec829ccd4d6efbad37d2b2326
```

## 3. Search

- Iterative deepening, alpha-beta negamax, PVS and widening aspiration windows.
- A 180,000-entry transposition table with bounded FIFO eviction, depth/bound
  metadata, halfmove-qualified cutoffs and ply-normalized mate scores.
- Staged TT/capture/promotion/killer/history ordering. Explicit yielded-legal-move
  counts determine terminal positions. The final main search has no pruning
  `continue`; quiescence establishes mate/stalemate before capture pruning.
- Check-aware quiescence searches all evasions and promotions, including quiet
  underpromotions. Stand-pat is forbidden in check.
- Conservative late move reductions, limited checking extensions, and null move
  disabled in check, pawn-only endings and artificial null subtrees.
- Delta pruning and deep-only static exchange pruning preserve checking
  sacrifices, promotions and evasions. SEE is used only from quiescence depth two.
- Third-occurrence repetition counting includes recorded game history and the
  current path. A second occurrence is not scored as a guaranteed draw.
  Draw contempt discourages giving away wins.
- Fifty-move draws are recognized at halfmove_clock >= 100, with checkmate
  taking precedence. The API still returns a legal move from drawn-but-legal FENs.

## 4. Evaluation

Incremental middlegame/endgame material and original piece-square formulas,
bishop pair, cached isolated/doubled/passed-pawn structure, dynamic passed-pawn
blockers, rook open/semiopen files, basic king pawn shelter, endgame king
centralization and bare-king mop-up. Insufficient-material scaling and evaluation
fading near the fifty-move limit discourage futile shuffling.

Established individual terms cost approximately 0–5% in local ablations.
Pawn caching preserved scores on 700 random evaluations and improved the
evaluation microbenchmark from about 193,000 to 532,000 evaluations/second.
GC tuning and an inconclusive futility experiment were rejected.

## 5. Time management

The 500 ms increment is added after the move and is not borrowed. The allocator
keeps a 150 ms safety reserve. For clocks of at least 1.5 seconds:

```text
soft = remaining_seconds / 35 + 0.75 * 0.5
hard = min(1.6 * soft, remaining_seconds / 8, remaining_seconds - 0.150)
```

Soft is bounded by the newly capped hard limit only where necessary. The
pre-existing low-clock path is retained below 1.5 seconds.

| time_left_ms | Soft seconds | Hard seconds |
| ---: | ---: | ---: |
| 120000 | 3.803571 | 6.085714 |
| 60000 | 2.089286 | 3.342857 |
| 30000 | 1.232143 | 1.971429 |
| 10000 | 0.660714 | 1.057143 |
| 5000 | 0.517857 | 0.625000 |
| 1000 | 0.098000 | 0.140000 |

At 300 ms the soft/hard budgets are 11.7/18.0 ms. Below 100 ms the engine
returns its legal fallback without searching. A single legal move returns
immediately. Iteration-growth estimates avoid starting unlikely-to-finish
depths; best-move changes or score drops permit modest extensions within hard.
Clock checks occur every 256 nodes, every 32 on low budgets, and at root moves.
An interrupted iteration replaces the prior choice only with a completed,
better-scoring root result.

Arithmetic simulations charge every hard limit plus 20 ms call overhead for
300 own moves at 120 s + 0.5 s and from low starting clocks. All retain the
150 ms reserve before the next increment: minima are 3.340 s from 120 s,
0.840 s from 1 s, and 0.262 s from 0.3 s.

Latest API timing-suite maximum hard-limit overrun: **2.831 ms**, including
the first call after import. That first call took 4.504 s against a 6.086 s
hard budget. The separate fixed-2.5-second benchmark below had a maximum
7.191 ms overrun. Maximum observed throughout the sprint was approximately
7.2 ms. These are local observations, not guarantees on slower hardware.

## 6. Correctness and regression results

[Full suite results](results/final_tests.json), run on the exact V0.3 source
after the repetition corrections and final retry fix:

| Metric | Result |
| --- | ---: |
| Assertions | 48,548 |
| Checked public API calls | 408 |
| Illegal moves | 0 |
| Unexpected exceptions | 0 |
| Observed flags in timed checks | 0 |
| Additional scaled-clock API stress calls | 54 |
| Stress illegal moves / unexpected exceptions / flags | 0 / 0 / 0 |

Coverage includes both colors, checks, mate in one/two, stalemate avoidance,
castling, en passant, all promotions, knight-underpromotion mate, quiescence
rook underpromotion, high halfmove clocks, drawn-but-legal positions, terminal
sentinels, 14,842 incremental move checks, staged-generator completeness, TT
bounds/mate normalization/capacity, and 349 random nonterminal positions.
One deliberately injected exception verified fallback legality and history
recording; it is not counted as an unexpected exception.

The cross-call repetition test builds positions by actually playing legal
moves from a queen-up position; early choices are scripted to reach the fixture,
then the final call uses normal search. Counters advance and the initial board
recurs at halfmove/fullmove counters 0/1 and 4/3 with identical position keys.
With the target already seen twice, Nh2-f3 would repeat for the third time.
The engine chooses Qb2, keeping its winning advantage. The untouched V0 snapshot
also passed this strengthened test. Retry tests cover identical positions with
different counters, irrelevant EP fields, fallback moves and castling-rights
loss on either side.

KQ vs K mated in **15 plies**, KR vs K in **27 plies**, both with at most
0.7 seconds per searching side per move and before the fifty-move rule.
Four accelerated random-opponent games ended in mates with zero illegal moves,
exceptions or flags. One capped candidate-vs-V0 regression run played four
80 ms/search games (2W/1D/1L) without crashes or illegal moves. That tiny
fixed-search-budget match is not Elo evidence or a real-clock timing test.

Total full-game timing/match wall time was conservatively counted as about
152.1 seconds, below the 300-second cap. One of the maximum two A/B runs was
used. No full games ran at the real competition clock.

[Scaled-clock and memory stress summary](results/stress_summary.json):
clock factors 1x/3x/6x, maximum scaled hard overrun 2.635 ms. Artificial TT
overfill kept exactly 180,000 entries and a bounded eviction queue; measured
peak RSS was 179,568,640 bytes (about 180 MB). The clock scaling is a simulation,
not a measurement on EPYC hardware. Zero-clock calls necessarily use best-effort
fallbacks; final 0/1/50 ms calls took approximately 0.09–0.10 ms.

## 7. Final benchmarks

Fresh engine state for each position, with a 2.5-second search budget.
Some searches stop earlier when the next depth is unlikely to finish.
Depth is fully completed depth; node totals include work in an interrupted
next iteration. NPS is (main nodes + quiescence nodes) / search elapsed time.
TT hit rate refers to main-search probes. Changes count best-move changes
after the first completed iteration.

| Position | Depth | Nodes | Qnodes | NPS | Wall s | Move | TT hits | Changes |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| opening | 8 | 25,874 | 108,872 | 53,897 | 2.502 | g1f3 | 45.4% | 0 |
| tactical | 5 | 4,787 | 39,934 | 44,772 | 1.000 | e2a6 | 48.5% | 0 |
| quiet | 7 | 14,263 | 117,065 | 52,414 | 2.507 | a2a4 | 34.0% | 2 |
| endgame | 12 | 53,685 | 52,549 | 67,598 | 1.573 | f3g3 | 79.1% | 1 |
| imbalance | 7 | 18,492 | 117,956 | 54,570 | 2.503 | d1a1 | 32.5% | 2 |
| king_safety | 8 | 18,363 | 90,196 | 55,379 | 1.962 | c3e4 | 40.8% | 0 |
| passed_pawns | 9 | 26,717 | 58,746 | 67,361 | 1.270 | c5c6 | 55.5% | 0 |

[Full machine-readable benchmark](results/final_benchmark.json) includes all
FENs and each iteration's score, move and elapsed time. Local NPS is a best case
for the competition's single AMD EPYC 2.6 GHz core.

## 8. Import and initialization

Fresh-process initialization including python-chess took **55.105 ms** in
the complete suite and **57.950 ms** in the ZIP smoke test. Agent-only import
with chess already loaded took **6.347 ms** in the final benchmark.
Static evaluation, pawn-mask and reduction tables are built during import,
not deferred to the first move.

The archive was imported directly with its root first on sys.path while
working in /private/tmp. It loaded only agent.py from the ZIP and returned
legal g1f3 on its first call at a 1,000 ms clock in **113.828 ms**, below the
140 ms hard budget. The archive member's hash equals the tested source hash.

## 9. Known weaknesses

Pure-Python tactical depth remains limited; the tactical benchmark completed
depth five. Evaluation and king safety are simple. No opening book, neural
evaluation or endgame tablebases are present. Complex endgames, fortress
recognition and repetition-dependent transpositions remain potential weaknesses.
Repetition-sensitive TT cutoffs are guarded, but full history is not encoded in
every TT entry. No claim of benchmark-opponent win rate or Elo is made before
the external match.

## 10. Compatibility risks

Tested with Python 3.12.14 and chess 1.11.2. Only stdlib and python-chess are
required. The private transposition-key method has a tested equivalent fallback.
Standard chess and valid input FENs are assumed; Chess960/variants are not part
of the contract. Each game must use its promised fresh process. No network,
files, subprocesses, native engine code or additional installation is needed
at runtime. The actual competition EPYC and referee have not been available
for validation.

## 11. Interface and minimal harness

Exact interface:

```python
get_move(fen: str, time_left_ms: int) -> str
```

With the unzipped submission root on sys.path:

```python
import chess
from agent import get_move

board = chess.Board()
move = chess.Move.from_uci(get_move(board.fen(), 120_000))
assert move in board.legal_moves
board.push(move)
```

For a position with no legal moves, the result is "0000". Otherwise it is a
legal UCI move, including when insufficient material or a draw counter would
already make the referee stop the game.

