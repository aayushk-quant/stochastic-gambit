# Chessathon final sprint

Start time: **2026-09-10 21:42:33 BST (20:42:33 UTC)**, from the mandatory first `date` command.
Hard stop: **2026-09-10 23:42:33 BST (22:42:33 UTC)**.

Scope: clean-sheet pure Python chess engine; no other chess engines, prior agents, or chess projects will be inspected. Hard limit: two hours from the recorded start.

Initial architecture: benchmark python-chess push/pop and bitboard evaluation, then commit within 15 minutes. Single-file runtime with bounded TT, iterative deepening PVS, quiescence, game history and strict wall-clock limits.

## 21:47:49 BST — representation committed (5m16s)

Python 3.12.14, chess 1.11.2, installed exclusively from a pre-existing local cached wheel. Default system Python was 3.9 without chess. No downloads, no other engine or project code inspected.

Microbenchmark: legal generation + push + counter-free key + pop: 237,522 nodes/s; push/pop: 326,873/s; bitboard material: 1,343,347 evals/s. Committed to python-chess Board for the sprint. Incremental material/PST and cheap bitboard terms will limit evaluator overhead.

## 22:01:55 BST — first playable search (19m22s)

Implemented iterative deepening PVS, bounded TT with mate-distance adjustment,
check-aware quiescence including quiet promotions, null move, conservative LMR,
incremental material/PST, bitboard evaluation, hard/soft time allocation, and a
legal exception fallback. Initial 0.3s diagnostics: 38–48k NPS, opening depth 6,
tactical depth 3, quiet depth 4, pawn ending depth 9. Correctness suite underway.

User rule updates incorporated: each game has a fresh process, so no new-game
detection. Increment arrives after moving. Source is original and readable;
DESIGN.md explains it. Increased reserve to 150ms for slower EPYC target.
Repetition draws require the third occurrence across real history plus search
path; irreversible castling-rights loss also clears history. Optional second
path-occurrence pruning skipped because V0 is not yet snapshotted. Checkmate
already takes precedence over the halfmove-clock draw in search.

## 22:05:52 BST — V0 passes and is snapshotted (23m19s)

Snapshot: `dev/snapshots/v0/agent.py`, with DESIGN.md. Full suite: 33,917
assertions, 396 API calls, 14,991 incremental move checks; zero illegal moves,
unexpected exceptions or flags. Additional tests: actual knight underpromotion
mate f7f8n; a forced-move call in 0.05ms; explicit injected search failure returned
and recorded a legal fallback. Mate-in-two fixtures independently verified and
checked not to contain mate in one.

KQ converted in 17 plies (7.50s test wall), KR in 27 plies (12.34s), using <=0.7s
per side per move and both sides searching. Four accelerated random-opponent
games at 1.2s + 0.005s all ended by mate with no flags/illegal moves/exceptions;
2.80s total wall. This is correctness evidence, not strength evidence.

Arithmetic 300-move simulations from 120s, 60s, 10s, 1s and 0.3s charged each
hard limit plus 20ms overhead; all stayed above 150ms reserve. Measured maximum
competition-scale hard-limit overrun 7.2ms. At 50/1/0ms remaining, API calls took
about 0.10–0.12ms. Import from /private/tmp: 5.1ms; first call at 1s clock: 75.4ms
vs 140ms hard budget. Submission contains only agent.py; no caches.

Full-game timing wall used so far: approximately 22.64s of the 300s cap.

## 22:11:49 BST — V0 audit and first optimization (29m16s)

Strengthened tests were run against the immutable V0 snapshot. An end-to-end
get_move test actually plays legal moves with Board.push/push_uci from a queen-up
position: g1f3/g8f6, f3g1/f6g8, g1f3/g8f6, f3h2/f6g8. The start recurs under
counters 0/1 and 4/3. The final Nh2-f3 would cause the third recorded occurrence;
V0 instead chooses Qb2, preserving its winning material advantage. No repetition
bug found. Snapshot remains untouched.

Refreshed timing report explicitly includes a fresh-process first call after
import, performed from /private/tmp: initialization including chess 52.1ms,
first call 924.3ms vs 3189.5ms hard limit, no overrun. Maximum overrun across that
test run: 3.2ms; maximum observed across all runs remains 7.2ms. Zero flags.

Candidate optimization: cache pawn structure while recomputing occupancy-based
passed-pawn bonuses. 700 random-position evaluations exactly match V0; eval
microbenchmark improves from 192,984 to 531,699 evals/s. Added constant-time FIFO
TT eviction to prevent dict-tombstone scans at capacity. Added a legal-move
guard before null pruning, ensuring a stalemate cannot be pruned as a win.

## 22:17:22 BST — V0.1 accepted and snapshotted (34m49s)

Applied the user's final allocator formula: soft = remaining/35 + 0.75*increment;
hard = min(1.6*soft, remaining/8, remaining-reserve). The <1.5s low-clock path is
unchanged. Soft is bounded by the newly capped hard limit only where necessary.

Clock ms | soft s | hard s
---|---:|---:
120000 | 3.803571 | 6.085714
60000 | 2.089286 | 3.342857
30000 | 1.232143 | 1.971429
10000 | 0.660714 | 1.057143
5000 | 0.517857 | 0.625000
1000 | 0.098000 | 0.140000

Full suite after this exact change: 33,534 assertions, 408 API calls, zero illegal
moves, unexpected exceptions or flags. Includes actual cross-call third-occurrence
avoidance with advancing counters; 14,615 incremental move checks; verified mates,
queen capture, knight fork, rook skewer, knight underpromotion and quiescence rook
underpromotion. KQ mate in 17 plies; KR mate in 35 plies, both below fifty moves.

300-move arithmetic simulations charge every hard limit plus 20ms overhead.
From 120s, minimum before increment 3.340s; from 1s, minimum 0.840s; from 0.3s,
minimum 0.262s. All exceed the 0.150s reserve. They converge to 3.840s after
increment. Fresh-import first call: 6.0917s vs 6.0857s hard; max overrun 5.96ms
including that call. Initialization including python-chess: 54.3ms.

Snapshot: dev/snapshots/v0.1, V0 remains untouched. Includes identical-score pawn
caching (fixed-depth NPS +7–20%), constant-time TT eviction, a stalemate-before-null
guard and exact tuple ordering in the private-key fallback. Full-game timing
wall used cumulatively: approximately 74.4s of 300s. No A/B matches run yet.

## 22:27:44 BST — 45-minute milestone

V0/V0.1 are safe snapshots and all mandatory search/time mechanisms are working.
Capture pruning experiments: broad SEE at the quiescence horizon regressed the
tactical position, so it was rejected. Restricting SEE to qdepth >= 2 preserved
the depth-five scores/moves on tactical, quiet and imbalance tests, and improved
time to depth about 7–10% versus preserving checking captures without SEE. Delta
pruning now preserves checking sacrifices. Static-exchange verification examined
83,442 legal captures, with zero unsafe negative classifications; a threshold
shortcut is a conservative upper bound, independently checked as well.

Evaluation ablations: all terms 39.0k NPS; no bishop pair 38.4k; no rook files
38.8k; no shelter 40.2k; no mop-up 39.1k; no pawn structure 41.0k. Individual
established terms have small cost, with node-mix/noise caveats; retained all.

Candidate staged move generation tries TT/captures/killers before quiet moves,
avoiding later generation on early cutoffs. Legal-set equality and incremental
evaluation/push-pop checks passed 30,314 assertions over 14,842 moves. Measuring
search performance before accepting the change.

## User-requested pause — after 22:33:28 BST clock check

Current candidate passed 48,536 assertions and 408 API calls, with zero illegal
moves/unexpected exceptions/flags; saved as V0.2. KQ/KR converted in 15/27 plies.
Current full-game timing wall used ~93.3s of 300s. V0 and V0.1 untouched. Detailed
state, rules, measurements, remaining work and the original clock deadline are
in `dev/RESUME.md`. Pausing now for the user's usage reset.

## 22:38:08 BST — resumed and interruption audit

Activated the workspace Python 3.12.14 environment. Source hash still matched
V0.2 exactly; V0 and V0.1 hashes unchanged. The interrupted patch had applied
nothing. Process inspection found no lingering benchmark/test processes.
Applied the maximum-ply draw/stalemate corner-case fix, preserving checkmate
precedence, with focused regression checks. Moved the diagnostic `_analyse`
function to dev/bench.py; runtime source no longer contains that development hook.

## 22:44:28 BST — final search experiment

First A/B regression: four 80ms-per-move games against V0, 14.1s wall, no crashes
or illegal moves. Two wins, one draw, one loss are NOT strength/Elo evidence.
This match uses fixed search budgets; actual clock flag checks are separate.
Total full-game timing/match wall conservatively counted: about 107.4s of 300s.

Tested depth-one non-PV quiet futility with a conservative 180cp margin, preserving
captures, pawns, promotions, checks and evasions. Tactical solutions remained
correct, but time-to-depth gains were unclear and the tactical test slowed.
Rejected and reverted the pruning. Retained an explicit yielded-legal-move count
for terminal detection, as requested in the user's staged-generation audit.
Main search once again has no pruning continue. Freezing search features now;
remaining work is validation, stress checks, packaging and reporting.

## 22:52:54 BST — final V0.3 validation

Found and reproduced a retry/castling-rights bookkeeping edge case. Retain now
compares post-move castling rights to the supplied pre-move board, not the previous
attempt's retained result. Focused tests cover same-move retry, a changed retry
choice, and opponent rights loss; all pass. Earlier snapshots remain untouched.

Full suite on final V0.3: 48,548 assertions, 408 checked API calls; zero illegal
moves, unexpected exceptions or flags. Actual cross-call repetition avoidance
still passes. KQ mate in 15 plies; KR mate in 27 plies. Full results saved in
dev/results/final_tests.json. Latest max hard-limit overrun including first import
call: 2.83ms; maximum previously observed in sprint: 7.2ms.

54 additional API stress calls at clock rates 1x/3x/6x: zero illegal moves,
unexpected exceptions or flags, max scaled overrun 2.63ms. Artificial TT overfill
kept exactly 180,000 entries and bounded FIFO queue; peak RSS 179,568,640 bytes.
GC threshold/freeze experiments showed no gain and were not adopted.

Full-game timing/match wall used conservatively: about 152.1s of 300s; one A/B
match run out of a maximum two. Submission has one file, agent.py, 32,210 bytes.
Final feature set is frozen. Completing reports and archive verification.

## 23:01:37 BST — final archive verified; ready for external strength test (79m04s)

Latest interruption audit: source still matches the V0.3 snapshot byte-for-byte;
V0 and V0.1 hashes unchanged. Recovered the completed final benchmark process
without rerunning or losing its results. All seven positions and per-iteration
diagnostics are saved in dev/results/final_benchmark.json. Completed depths:
opening 8, tactical 5, quiet 7, endgame 12, imbalance 7, king safety 8, passed
pawns 9. Local NPS ranged from 44,772 to 67,598. Maximum benchmark hard-limit
overrun was 7.191ms; the separate final API timing suite maximum was 2.831ms.

Created dev/chessathon-submission.zip: exactly agent.py at the archive root,
32,210 bytes uncompressed and 8,259 bytes zipped. Direct archive import from
/private/tmp with the ZIP first on sys.path passed: Python 3.12.14, chess 1.11.2,
57.950ms initialization including chess, first 1,000ms-clock call 113.828ms
against a 140ms hard budget, legal g1f3. The ZIP member hash matches tested source.
Smoke-test measurements are in dev/results/package_smoke.json.

Final source SHA-256:
7a862a0c104ac76b5d2e7174f9cc31f7bdfe592a12c4dc125ca8b51ac470e279

Final report: dev/REPORT.md. Judges' walkthrough: dev/DESIGN.md.
No runtime changes after the final passing suite. Original hard deadline remains
23:42:33 BST; completion is early. V0_READY_FOR_STRENGTH_TEST. Stop development
and await the user's external, color-balanced benchmark match.
