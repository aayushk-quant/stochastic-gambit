# Current state: ready for external strength test

Completed at 2026-09-10 23:01:37 BST, 79m04s after the original start. Both
interruption audits passed. No active development or benchmark processes remain.
Do not restart the sprint or act on the historical remaining-work list below.

Final source: submission/agent.py, identical to dev/snapshots/v0.3/agent.py.
SHA-256: 7a862a0c104ac76b5d2e7174f9cc31f7bdfe592a12c4dc125ca8b51ac470e279.
V0 and V0.1 are unchanged. Final full suite: 48,548 assertions, 408 checked API
calls, zero illegal moves/unexpected exceptions/flags; 54 additional stress
calls also clean. Package smoke test from /private/tmp passed.

Deliverable: dev/chessathon-submission.zip (agent.py only). Full report and
measurements: dev/REPORT.md and dev/results/. Judges' walkthrough: dev/DESIGN.md.
Final status: V0_READY_FOR_STRENGTH_TEST. Await external match results.

## Historical pause checkpoint (superseded; retained for audit)

Sprint start: 2026-09-10 21:42:33 BST. Last work clock check: 22:33:28 BST
(50m55s elapsed). Original wall-clock hard stop: 23:42:33 BST. User explicitly
requested a pause to reset usage, then a seamless continuation. Re-check `date`
on resume; do not silently assume a new two-hour budget.

## Workspace and constraints

Use `.venv/bin/python -B` (Python 3.12.14, chess 1.11.2). Python-chess came from a
pre-existing cached wheel; no network/downloads or other chess engine/project
source has been inspected. No third-party engines/ports, native engine code,
blobs, external data, or published PSTs. Original formula-generated PSTs.
No agents/delegation used or authorized. Only `submission/agent.py` ships.
Runtime must have no development code, files, caches or writes. Tests import
through absolute paths and have passed from /private/tmp. Default system python3
is 3.9 without chess; do not use it.

## Latest rules from user (supersede original prompt)

- Each game has a fresh process. No new-game detection. First FEN starts history.
- Record each supplied current position unless identical to preceding call (retry).
  Record the result of every returned move, including exception fallbacks.
- Counter-free keys use Board._transposition_key with a tested equivalent fallback.
  Actual repetition draw is the THIRD occurrence across game history and search
  path. No second-occurrence draw pruning was adopted.
- Clear history after pawn moves, captures, or permanent castling-rights loss.
- Halfmove >=100 is a draw in search, with checkmate taking precedence. API must
  still return a legal move whenever one exists (even automatically drawn FENs).
- Increment is added after our move. 600 plies is a draw. One EPYC 2.6GHz core;
  local NPS is best-case. Import precomputation has a separate 90s allowance.
- Latest allocator: soft=remaining_seconds/35 + 0.75*0.5; hard=min(1.6*soft,
  remaining/8, remaining-0.150). Bound soft by newly capped hard where necessary.
  Existing <1.5s low-clock branches retained. User specifically authorized and
  required this in V0.1; do not revert to old capped-soft allocator.

## Safe snapshots and current candidate

V0: `dev/snapshots/v0/agent.py` (immutable). V0.1:
`dev/snapshots/v0.1/agent.py` (immutable). Current candidate just saved as V0.2:
`dev/snapshots/v0.2/agent.py`, identical to submission/agent.py at pause.

Latest COMPLETE suite on this exact candidate: **48,536 assertions; 408 API calls;
0 illegal moves, 0 unexpected exceptions, 0 flags**. Includes 14,842 incremental
move checks, staged-generator completeness, fast legal-existence proof checks,
mates 1/2 both colors, 12 tactical cases, actual knight underpromotion mate,
rook underpromotion in qsearch, fallback recording, TT bounds/mate score tests,
349 random positions from a request of 350, clock simulations, first-import call,
KQ/KR conversions. One intentional injected exception is tested separately and
excluded from unexpected exception counts.

KQ converted in 15 plies (6.97s total test wall), KR in 27 plies (11.92s), <=0.7s
per move for both searching sides. Latest max hard-limit overrun: 1.56ms including
fresh-import call (first call 5.379s vs hard 6.086s). Import including chess 57ms.
Maximum overrun observed across earlier runs was 7.2ms.

Arithmetic 300-own-move simulations charge every hard limit plus 20ms overhead.
At 120s initial, minimum before increment 3.340s; at 1s initial 0.840s; at 0.3s
initial 0.262s. All above 150ms reserve. Long games converge to 3.840s after increment.

Actual cross-call repetition test starts queen-up, plays g1f3/g8f6,
f3g1/f6g8, g1f3/g8f6, f3h2/f6g8. Counters advance; initial position recurs at 0/1
and 4/3. Nh2-f3 would create a third occurrence; engine chooses Qb2 and preserves
winning material. Tested against untouched V0 and all later candidates.

## Architecture and accepted improvements

python-chess push/pop committed at 5m16s (no representation switch). Single file.
Incremental tapered material/PST; pawn structure cache, bishop pair, rook files,
king shelter, passed pawns, endgame centralization and bare-king mop-up.
ID/PVS alpha-beta, aspiration, bounded 180,000-entry TT with constant-time FIFO
eviction and mate-distance normalization, null move (not in check/pawn-only,
legal-existence guard), conservative LMR, limited checking extensions, killers/history.
Check-aware qsearch includes captures, quiet promotions and all evasions. Delta
pruning preserves checking sacrifices. SEE pruning only at qdepth>=2, with
margin -60, and never skips checks/evasions/promotions. Original SEE verified on
83,442 captures against independent legal recapture minimax: zero unsafe negative
classifications. Broad SEE at qdepth0 regressed tactics and was rejected.

Staged move generation: TT, captures/promotions, legal quiet killers, then quiet
history ordering. User specifically audited terminal detection: main search has
NO pruning `continue`; each yielded move assigns bestmove or propagates timeout
past terminal detection. Thus bestmove is None iff zero legal moves yielded.
If later adding a pruning continue, use yielded-move count for terminal detection.

Fast legal-existence proof at non-check qnodes: an unpinned pawn with an empty
forward square proves a legal move exists; otherwise use full legal generation.
Verified against actual legal generators over thousands of positions.

GC tuning measured default/raised/frozen+raised at ~45.1/45.1/45.0k NPS: NO
benefit, so no runtime GC tuning adopted. Eval ablations found 0–5% individual
term costs; retained established terms. No A/B matches run yet.

Latest fixed-depth-five results (seconds/NPS): opening .0456/58,260; tactical
.8726/44,694; quiet .4913/51,298; endgame .0176/68,673; imbalance .3290/55,153;
king safety .1497/52,862; passed pawns .0183/71,428. V0.1 comparison: opening .0633,
tactical 1.0028, quiet .8555, endgame .0245, imbalance .4235, king safety .1744,
passed pawns .0228. Clear overall time-to-depth improvement.
One 2.5s quiet-position test completed depth 7 (~47.6k NPS), versus V0.1 depth 5.
Final full seven-position 2.5s benchmark still needs to be recorded.

## Remaining work (do not redo completed experiments)

1. Small correctness fix identified but NOT YET IMPLEMENTED: qsearch's MAX_PLY
   guard precedes repetition/halfmove detection and may evaluate a drawn node at
   ply 100. Move draw detection ahead of MAX_PLY and handle stalemate at MAX_PLY.
   Checkmate must retain precedence. Add focused tests for these extreme nodes.
2. Clean runtime closure before final: `_analyse` is a development diagnostic hook
   still in agent.py. Move its body into dev/bench.py and use it there, remove it
   from submission. Avoid unrelated refactoring. In-memory stats are used by tests.
   DESIGN.md needs updating for staged generation, deep-only SEE and pawn caching.
3. Further SMALL measured improvements only if worthwhile. A smoothed iteration
   growth predictor was considered but NOT implemented (current staged search
   already reaches depth 7 on quiet test; no evidence change is needed).
4. Run final appropriate correctness/low-clock checks and 2.5s benchmark for all
   seven categories. Record depth, nodes, qnodes, NPS, wall, move, TT rate, changes.
5. At most one final candidate-vs-V0 A/B regression match is planned, <=5min wall,
   ideally 30–60s cap at ~0.05–0.1s/move. Do not use tiny score as Elo evidence.
6. Total full-game timing wall used ~93.3s of 300s (conversions plus accelerated
   random games). At most two A/B matches allowed; ZERO run. Keep all testing caps.
7. Snapshot final passing source; ensure submission contains only agent.py and
   no caches. Report total bytes, import time, known weaknesses/compatibility,
   exact signature and minimal import/call harness. Final response must begin
   `V0_READY_FOR_STRENGTH_TEST`, then stop for external 40–60-game match.

Useful commands:
`.venv/bin/python -B dev/tests.py --group all`
`.venv/bin/python -B dev/bench.py --seconds 2.5`
`.venv/bin/python -B dev/bench.py --depth 5 --engine dev/snapshots/v0.1/agent.py`
`.venv/bin/python -B dev/match.py --opponent dev/snapshots/v0/agent.py --cap 60 --seconds 0.08 --games 4`
`.venv/bin/python -B dev/see_probe.py --positions 20000 --engine submission/agent.py --threshold -60`

All project edits use apply_patch. Snapshots are copies, never overwrite older
ones. Do not inspect other chess projects or engine source. No pending processes
or running tools remain at pause.
