# Frozen external strength test in progress

## LATEST USER UPDATE — overnight extension authorized and armed

The user extended the task until 07:00 BST on 11 September 2026: do not admit a
new pair at/after 07:00, but finish both games of any pair admitted before then.
The original 40 remain the primary preregistered test and must finish unchanged.
Do not edit run_match.py, worker.py or test_runner.py; their hashes are checked
by the original final report. Both engine sources/archives are frozen throughout.

A SEPARATE supervisor is armed: extend_to_0700.py, PID 27385, caffeinate PID
27386, unified exec session 93575, functions store extension_session=93575.
It waits for ORIGINAL results.json AND match_summary.md AND original coordinator
PID 25252 to exit before starting any extension game. Never launch another copy.

Separate namespace:
/Users/aayushkumar/Documents/PYTHON/stochastic-gambit/aichessathon-starter/benchmark_results/astra_v03_vs_build3/extension_to_0700/

Extension order is frozen in its schedule.json: first the TWO unused eligible
openings from the frozen corpus, opposite-castling-race then kingside-pawn-storm.
The screen is identical to the original: valid/live/non-check position, not
tactical/endgame/defensive category, material within one pawn, >=28 pieces, no
mate in one, counter-free deduplication. After unused positions are exhausted,
cycle the complete 22-eligible-opening list in frozen corpus order; explicitly
mark repeat_opening/repeat_cycle. No result-dependent selection or early stopping.

extension_report.py audits and reports primary, extension, and combined results
separately. All games/repeat pairs of an opening identity are ONE independent
unit for uncertainty. A self-test verifies duplicating games cannot narrow the
opening-clustered interval. Original artifacts are hashed after coordinator exit
and verified unchanged at final extension reporting. No engine changes/uploads.

The extension's two scripts and schedule are also hash-frozen now. Do not edit
them during the run. Outputs include separate games.jsonl/games.pgn/results.json,
combined_results.json, match_summary.md, preflight.json, launch_preflight.json,
progress.log and per-game traces. The supervisor persists games immediately.

At 00:32:41 the supervisor armed successfully. At ~00:33 the original run had
12 games complete: Astra 8-3-1, zero flags/illegal/crashes; pair 7 was active.
Keep monitoring both sessions. User intends to sleep; leave the overnight run
active through the time cutoff and its final pair. The earlier 40-game-only
stop instructions below are historical and superseded by this section.

## Original run details

The user authorized exactly 40 games / 20 colour-swapped opening pairs at
120000 ms + 500 ms, competition_600, against the exact final Build3 ZIP.
No engine development, tuning, archive changes, uploads, or extra games.

Match started 2026-09-11 00:02:42 BST. Coordinator PID 25252, caffeinate PID
25254. Unified exec session 16258; functions store external_match_session also
contains that ID. No duplicate launch. If interrupted, first inspect the existing
process/progress rather than starting a second run. The coordinator runs all
20 pairs automatically and persists every game immediately.

Output namespace:
/Users/aayushkumar/Documents/PYTHON/stochastic-gambit/aichessathon-starter/benchmark_results/astra_v03_vs_build3/

Monitor progress.log, games.jsonl, completed/, move_traces/. The coordinator
prints a heartbeat every 30 seconds. Maximum 2 games, always the two games of
the same opening pair. Each game uses two fresh isolated Python processes;
SIGSTOP between moves prevents pondering. caffeinate watches the coordinator.
The user asked whether they could sleep and was told to leave the Mac plugged
in, lid open, and this session running. Continue monitoring through completion.

Preflight passed: source and both ZIP hashes exact, separate clean read-only
temporary extractions, both get_move signatures/imports/legal startpos moves
verified, no competing chess processes at launch, frozen 40-slot schedule and
20 unique openings, 12 scripted harness tests passed. These tests cover mate on
ply 600, no material adjudication, opening accounting, repetition, fifty-move
draws, illegal/crash/flag losses, and increment only after legal moves.

Candidate source SHA256:
7a862a0c104ac76b5d2e7174f9cc31f7bdfe592a12c4dc125ca8b51ac470e279
Candidate ZIP SHA256:
3f3f7cba8798a90d69a59e3e5ca7525b5dcf6c8ec829ccd4d6efbad37d2b2326
Build3 ZIP SHA256:
ca4c81d7a28d979ae8284d07366f825bb0f6514ba2b75de1c562191747f6fef8

The user reconciled Build3 strength-parent 1ede533f169229d0c0ae3d30f23fc89328ee8f82
with deployment fefaeb8666947f13b962485b220566c9a2b72196: config.py intentionally
changes log_search True to False. The exact ZIP is authoritative; preflight.json
records this. No engine source was copied or changed.

Runner code: run_match.py / worker.py / test_runner.py in this directory.
Their hashes are frozen in preflight.json and checked before/after the run.
Do not edit them during the match. Audited harness/contract.py is reused unchanged;
the separate runner preserves complete metadata because the existing subprocess
referee drops contract/clock fields on ordinary endings. It uses the audited
Board.outcome(claim_draw=True) policy and first-FEN history.

The starter Python 3.12 venv is used. A saved permission prefix allows that venv
to run this specific run_match.py script, including writes to the new output
namespace. Existing benchmark artifacts are read-only; never overwrite them.

When finished, results.json and match_summary.md are exclusively created after
validation of all 40 slots, 20 complete pairs, colours, clocks, opening plies,
PGNs, unchanged packages, and 80 fresh worker PIDs. Read and independently audit
the output counts/hashes. Report W-D-L, score, pair sweeps, rough Elo, explicitly
approximate pair-level uncertainty, terminations, flags/illegal/crashes, remaining
clocks, total runtime, mean pair duration. The predeclared summary uses a
conservative Student-t/Wilson envelope to avoid degenerate zero-width intervals.

Do not stop based on score. Stop only for an operational failure. Do not launch
additional games. Final decision deadline is 2026-09-11 09:30 BST; upload closes
11:00 BST, but no upload is authorized. Finish with exactly one allowed practical
recommendation: SCALE_ASTRA_TEST, KEEP_BUILD3, or ASTRA_READY_FOR_FINAL_VALIDATION.
If scaling is recommended, give current time, capacity before 09:30 at measured
pair duration, and exact unused openings from the same frozen corpus. Default
to already-hardware-validated Build3 if the result remains inconclusive.
