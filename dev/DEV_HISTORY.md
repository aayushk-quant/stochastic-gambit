# Stochastic Gambit — Development History

**September 4–11, 2026 · retrospective assembled September 17, 2026**

Stochastic Gambit's final submission was Astra v0.3, but the project did not begin with Astra's last-evening sprint. Before that came a modular classical engine, live-game investigations, three successive classical builds, a neural experiment, several independent audits, and hundreds of comparison games. Much of that implementation never became part of the final submission. This account preserves the work and its results, including the unsuccessful ones.

This is a reconstruction from Git history, saved reports, tests, and benchmark artifacts in the original `Documents/PYTHON` project folders. Dates refer to London time where the records supply a timezone. Some experiments crossed midnight; grouped dates below avoid inventing a more precise sequence than the surviving records establish. The minute-by-minute Astra account remains in [DEVLOG.md](DEVLOG.md).

The final engine used **no neural network or machine learning**, a personal challenge set by the project author. The broader research history nevertheless includes a trained neural branch that was tested and rejected. That distinction matters: a description of what shipped should not erase what was tried. The author reports that the final submission finished in the **top 25% out of 500+ teams**; that competition result is separate from the local experiments documented here.

## The different names

| Name in the records | Meaning |
| --- | --- |
| Stochastic Gambit | The overall project and competition entry |
| Mark 1 / Variant B v3 | The early classical engine and its root repetition adjustment |
| Fable Mark II / Builds #1–#3 | Successive improvements to the earlier modular classical engine |
| Mark III | An experimental neural residual model used to review the classical engine's root decision |
| Astra v0–v0.3 | A separate, single-file classical implementation developed on September 10 |
| `chess-fr-fr` | The original folder containing the final Astra submission published in this repository |

**Build #3 and Mark III are different candidates.** Build #3 was the classical parent against which the neural Mark III experiment was tested. Astra was subsequently compared against the frozen final Build #3 archive.

## September 4: getting a search engine working, then making it trustworthy

The original `stochastic-gambit/aichessathon-starter` repository already contained the competition starter and harness. Its upstream commits predate the project week and should not be counted as original engine development. The first project search-core commit in the preserved history is `3dcfda4`, at 11:32 on September 4. [S1]

The engine quickly acquired iterative-deepening negamax, dynamic time allocation, capture/killer/history move ordering, a transposition table, repetition awareness, quiescence search, check extensions, null-move pruning, late move reductions, and aspiration windows. A benchmark corpus and tournament runner accompanied the search work.

Much of the same day then went into less visible correctness work. A position alone does not capture the history that determines whether a repetition or fifty-move draw is available. Transposition-table results needed the right rule-history context; the public wrapper needed to record the position created by its own reply; and artificial null moves could not be allowed to manufacture real repetition draws. Further regressions covered mate at the quiescence limit, terminal-position precedence, and bounded deadline polling.

The afternoon also brought faster bitboard evaluation and cheaper quiescence move generation, backed by differential checks. Fixed-node budgets were added to the benchmark tooling so an implementation change could be compared at equal work, instead of confusing a different search tree with a faster machine or a different clock allocation. These were foundations for the later experiments, even though the modular engine would eventually be replaced.

## September 5–6: measuring strength and investigating the wrong explanations

A Stockfish comparison runner was committed early on September 5. The saved ladder used 40 games at each requested strength setting, at 30 seconds plus 200 ms per move: [S2]

| Stockfish configured setting | Stochastic Gambit W–D–L |
| --- | ---: |
| 1600 | 25–10–5 |
| 2000 | 15–12–13 |
| 2400 | 5–11–24 |

All three batches recorded zero flags, crashes, and illegal moves. These are results against configured Stockfish opponents, not a calibrated human Elo rating for the project. Stockfish was an external testing tool; it was not part of the submitted engine.

Repetition and apparent shuffling became another line of investigation. Variant B v3 applied a small, root-only penalty to revisiting moves when the engine thought it was clearly winning: a +300-centipawn gate and a 25-centipawn penalty, with mate scores exempt. The intended behavior was to encourage progress without throwing away a saving draw. Tests checked the score transformation, its search-window translation, and exact classical behavior with the feature disabled. [S3]

The game investigations did not justify crediting this feature for every apparent escape from a shuffle. In rounds R31–R34, it changed the selected move zero times. R32's winning continuation was ordinary classical search; R33's repetition was the correct way to save a losing ending. The later R36–R45 investigation likewise found no verified selected-move benefit. This was a working, carefully tested mechanism whose usefulness was not demonstrated in those live samples. [S3, S5]

The loss analysis instead pointed toward evaluation weaknesses. In R31, the engine mishandled connected passed pawns. In R34, it remained optimistic while its king came under a decisive attack. Larger search budgets did not reliably correct the critical choices. That redirected work toward king safety and passed-pawn evaluation, while preserving positions where the existing engine already defended correctly.

## September 6–7: Fable Build #1 and a useful speed improvement

Build #1 changed the handoff from normal search into quiescence. The previous code constructed a complete legal-move list at the horizon, only to hand control to quiescence, which generated its own moves. The replacement first used a cheap legal-move existence check, preserved terminal and draw handling, and avoided the redundant list. Fixed-node comparisons checked that this optimization preserved search semantics. [S4]

The 200-game comparison ran from September 6 at 13:05 until September 7 at 00:26. The candidate scored **69 wins, 80 draws, and 51 losses: 54.5%**. Recorded mean throughput rose from 45,871 to 60,971 nodes per second, about **33%**, and completed depth rose by 0.26 ply. Both sides completed the match without crashes, illegal moves, flags, or timeouts.

The report's score interval, 47.6%–61.3%, still included equality. The result supported keeping a practical speed improvement with a caveat; it did not prove a precise Elo gain. The earlier forensic positions also showed why throughput alone was insufficient: searching more of a tree built around a mistaken evaluation could preserve the same bad decision. Build #1 was promoted in commit `e062685` shortly after midnight.

## September 7–8: king safety and passed pawns

The R36–R45 investigations strengthened the case for defensive king safety. Several critical errors occurred with substantial time still on the clock, and the engine could attack effectively in other games. This was more specific than a general claim that the engine was too slow or always bad at tactics. [S5]

**Build #2** added a bounded defensive king-danger term. Its audit checked signs, color symmetry, board restoration, score limits, and preservation of known saving repetitions and blockades. It found meaningful improvements on several targeted positions, but also caveats: one claimed improvement was sensitive to the reference analysis, and an independent small performance sample measured about an 8.1% search slowdown. [S6]

The completed 200-game Build #2 comparison returned **70–61–69, or 50.25%**, with zero recorded crashes, illegal moves, or flags. Better answers on selected positions had not produced a clear overall match advantage. The saved preparation README still says the match was not launched; the completed results JSON is the later evidence. [S7]

**Build #3** added bounded passed-pawn bonuses, discounted when the pawn was blocked. Runtime validation checked exact Build #2 parity with the new term disabled, integration behavior, and the cost of the new evaluation. It eventually passed 158 tests, lint, and type checking. The measured mean search throughput cost was about **5.07%**. [S8]

Two initial test failures also mattered. An old fixed-node golden expectation assumed the previous evaluator, and an empirical late-move-reduction comparison did not preserve its old move agreement under the changed evaluation. Those tests were explicitly pinned to their original baseline where appropriate. The report retained the selective-search disagreement as a limitation; it did not claim the change had made that disagreement disappear.

The original 100-game Build #3 match scored **32–40–28, or 52%**. A separate clean replacement of the first four games changed the adjusted total to **53 points out of 100**. That rerun replaced four results; it was not four additional independent games to append to the sample. Neither result established a decisive strength gain. [S9]

These early build matches used the historical 300-ply harness. Later work found that its end-of-game contract differed from the intended 600-total-ply contract. Their results remain useful historical comparisons, but should not be silently presented as measurements under the repaired harness.

## September 8: the neural branch and its first data problems

Mark III explored whether a small learned correction could improve Build #3's final move choice. The classical search remained the parent. A neural residual model would help nominate alternatives at the root, and additional search would verify potential replacements. This work lived in separate experimental worktrees and was not part of Astra. [S1, S12, S13]

The first 500-position labeling pilot exposed a poor starting distribution: only 439 positions were eligible, the usable residuals were strongly biased, and roughly 24% exceeded 400 centipawns in magnitude. Deeper labels also moved substantially in some positions. The next pilot switched to public games from The Week in Chess, issues 1660 and 1661. Its 500 positions came from 131 independent games; the large-residual share fell to about 8%, and the deeper-label audit was more stable. [S10]

A feature bug was fixed before scaling: the en-passant feature needed to represent a **legal en-passant capture**, not merely an en-passant square left in board metadata. The corrected schema checked that extracting features before and after a FEN round trip produced the same vector. Recorded competition games were screened for collisions with the candidate dataset.

The data work was substantial in its own right. It also illustrated how easily an apparently successful learning experiment could begin with an unrepresentative corpus or inconsistent features.

## September 9: training, a failure, and a controlled repair

The scaled labeling run took approximately **4.25 hours**. It labeled 50,601 positions and retained **50,345 eligible examples** from 3,886 source games. Training, validation, and test splits were made by whole source game, yielding 35,339 / 7,217 / 7,789 eligible rows. That avoided putting nearby positions from the same game on both sides of an evaluation split. [S11]

The residual network was small: **824 → 32 → 16 → 1**, with 26,945 parameters. Five seeds were trained, and selection used a frozen validation criterion. The first selected model, V1, **failed its offline gate**. Although its capped-error metric improved, ordinary validation mean absolute error rose to roughly 500 cp versus 151 cp for the classical reference; test error was also much worse. [S12]

The cause was unusually concrete. Features that were constant in training were normalized with an extremely small scale. When three validation endgames activated previously unseen features, the normalized values reached one million, producing extreme predictions. Good average behavior on common positions had hidden a severe failure on rare ones.

V2 changed the scaling of training-constant features to 1.0. The V1 artifacts were preserved, and a fresh holdout was used instead of repeatedly treating the already-examined test set as unseen data. On 4,382 eligible fresh-holdout positions, V2 reduced mean absolute error from **144.1 cp to 121.7 cp**, about **15.5%**. It passed the offline checks. That established a better position-value predictor under the test protocol, not a stronger chess player. [S12]

## September 9: checking what the runtime and benchmark actually did

Before strength testing, the runtime audit found another important defect: the model predicted a **residual**, but root review was treating that output as an absolute value. The integration needed to reconstruct the parent evaluation plus the residual, then apply the correct perspective conversion. The repair was accompanied by model/runtime parity, sign, fallback, budget, and classical-mode checks. [S13]

The game harness was also repaired. Its old move-stack count ignored opening moves supplied through a FEN and applied material adjudication after 300 engine plies. The new explicit contract counted opening plies toward a 600-total-ply cap and drew unfinished games at that cap. A separate paired-runner bug granted increment before checking move legality; that order was corrected. These are descriptions of the contract recorded in the September audit, not a statement of current competition rules. [S14]

Then the comparison setup revealed a potentially invalid experiment: the paired runner called the searcher directly and bypassed the root-review code in `agent.py`. Without a repair, a supposed neural comparison would have silently compared classical engines. The benchmark hook was fixed so review ran inside the measured move time. [S15]

An equal-work classical control retained the review procedure but returned zero learned residual. Other proposed controls were rejected because one almost never overrode a move and another largely reduced nomination to arbitrary tie-breaking. The selected control made it possible to ask whether an effect came from learned information or simply from doing extra review work.

## September 9–10: the experiment that said to stop

The final Mark III gate completed **400 games** after a recorded, pre-results reduction from the originally planned 800. Its three comparisons produced: [S16]

| Comparison | Games | Candidate W–D–L | Candidate score |
| --- | ---: | ---: | ---: |
| Mark III vs classical Build #3 | 160 | 25–55–80 | 32.81% |
| Mark III vs equal-work classical control | 160 | 43–68–49 | 48.13% |
| Equal-work control vs Build #3 | 80 | 9–28–43 | 28.75% |

The recommendation was **RECOMMEND_BUILD3**. Both review variants lost badly to the classical parent, while Mark III's difference from the control was inconclusive. The runtime review consumed substantial thinking time and changed the selected move relatively infrequently. The report identified the review architecture and its allocation of search time as a major problem; improved offline prediction accuracy had not translated into better play.

This was a failed candidate with a useful result. A repaired model, clean numerical tests, and promising validation metrics were insufficient reasons to ship it. The frozen implementation was rejected on game evidence. The result does not establish that neural evaluation can never help; it establishes that this particular integration did not earn its place.

Build #3 was then packaged as a classical fallback in `deploy-build3-final`. The final packaging change disabled per-move logging. The archived validation records 158 passing tests, legal-move and clean-room checks, and two smoke games; the report explicitly says the package had **not been uploaded** at that checkpoint. [S17]

## September 10, evening: Astra starts again

Astra began at **21:42:33 BST** in `chess-fr-fr`, under a two-hour limit. Its sprint record specifies a clean-sheet, readable, pure-Python engine without inspecting or copying the earlier engines. It was a separate implementation, not a renamed copy of Build #3 or a neural model with its weights removed. [S18]

The implementation used python-chess for legal moves and board updates, and added its own incremental tapered evaluation, formula-based piece-square tables, iterative-deepening search, bounded transposition table, repetition history, and time management. V0, v0.1, v0.2, v0.2.1, and v0.3 were preserved as snapshots.

The sprint had its own rejected ideas. Broad static-exchange pruning at the quiescence horizon hurt the tactical test and was restricted to deeper quiescence. A conservative futility-pruning experiment produced unclear speed gains and slowed a tactical case, so it was reverted. Garbage-collection tuning produced no useful gain. Pawn caching and staged move generation survived their checks. A retry/castling-rights bookkeeping defect was reproduced and fixed before the final freeze.

At **23:01:37**, after **79 minutes and 4 seconds**, the final archive was verified. The saved suite recorded **48,548 assertions, 408 checked API calls, and 54 additional stress calls**, without illegal moves, unexpected exceptions, or flags. The runtime was one 32,210-byte Python file, compressed into an 8,259-byte ZIP. These checks established correctness and packaging readiness; external strength testing came next.

## September 11: the overnight comparison and the final entry

Astra v0.3 was tested against the exact frozen Build #3 archive with the repaired game contract, paired openings, swapped colors, and fresh processes. The primary 40-game test scored **22–13–5 for Astra: 71.25%**. The overnight extension added 148 games, scoring **87–35–26**. [S19]

The combined descriptive total was **109 wins, 48 draws, and 31 losses in 188 games: 70.74%**. Both engines recorded zero flags, illegal moves, and crashes or uncaught exceptions. The run finished at **07:01:21 BST**, allowing the last admitted pair to finish after the 07:00 cutoff.

The uncertainty did not vanish with the larger game count. There were only **22 distinct opening identities**, and most extension games repeated existing openings. The combined conservative score interval was approximately **49.85%–85.47%**, still crossing equality. The archived reports therefore called Astra *nominally better but inconclusive* and retained the conservative recommendation **KEEP_BUILD3**.

The project author subsequently identifies Astra in `chess-fr-fr` as the final Stochastic Gambit submission. The public repository follows that identification. The available local match records do not establish the exact competition upload time or the reasoning that overrode the conservative match recommendation; this retrospective does not invent either. The author-reported top-25% competition finish is the final outcome, distinct from these local comparison scores.

## What the week left behind

The earlier modular engine did not become the final single-file submission. Its work still produced reproducible search regressions, a clearer account of live losses, measured performance tradeoffs, a corrected game contract, an independently evaluated dataset and model, and a decisive reason not to ship the neural review experiment.

Several ideas had weaker results than their implementation effort might suggest: the revisit adjustment had no demonstrated live move benefit in the investigated games; the king-safety and passed-pawn builds had inconclusive overall match gains; and the neural branch improved offline accuracy while reducing playing strength. Those outcomes belong in the development history alongside the successful final sprint.

## Source record

The earlier records remain in the original sibling projects; this document does not import their engines, datasets, or model weights into the final submission. Paths below are relative to the original `Documents/PYTHON` directory. `STARTER` abbreviates `stochastic-gambit/aichessathon-starter`. These are archival locations, not links expected to resolve inside this repository.

| ID | Original evidence |
| --- | --- |
| S1 | `STARTER` Git history: `3dcfda4` through `fefaeb8`; neural gate completion `77cb2f2`; blind sample-size amendment `97b07f5` |
| S2 | `STARTER/benchmark_results/sf_ladder_30s.json` |
| S3 | `STARTER/tests/test_revisit_adjustment.py`; `STARTER/benchmark_results/diagnosis/FINDINGS_CROSS_GAME_R31-R34.md` |
| S4 | `STARTER/benchmark_results/strength_gate/BUILD1_STRENGTH_GATE.md`; promotion commit `e062685` |
| S5 | `STARTER/benchmark_results/regression_games/diagnosis/R36_R45_CROSS_GAME.md` |
| S6 | `STARTER/benchmark_results/build2/BUILD2_KING_SAFETY.md`; `STARTER/benchmark_results/build2_audit/BUILD2_CODEX_AUDIT_RESULT.md`; commit `1e85d4c` |
| S7 | `STARTER/benchmark_results/strength_gate_build2/build2_results.json` |
| S8 | `stochastic-gambit/build3-runtime-validation-20260908/REPORT.md`; commits `2356e5e`, `950eec3`, `5c53f97`, `1ede533` |
| S9 | `STARTER/benchmark_results/strength_gate_build3/build3_results.json`; `STARTER/benchmark_results/strength_gate_build3_contamination_rerun/rerun_results.json` and `rerun_4.py` |
| S10 | `stochastic-gambit/mark3-label-pilot/benchmark_results/mark3_label_pilot/pilot_summary.md`; `stochastic-gambit/mark3-public-corpus-pilot/benchmark_results/mark3_public_corpus_pilot/pilot_summary.md`; feature fix `7700eae` |
| S11 | `stochastic-gambit/mark3-public-corpus-pilot/benchmark_results/mark3_training_data/final_summary.md` |
| S12 | `mark3-equal-work-control/benchmark_results/mark3_training/training_summary.md` and `mark3_training_v2/training_summary.md` (preserved V1/V2 reports); original experiment folders `stochastic-gambit/mark3-train-residual-v1` and `stochastic-gambit/mark3-train-residual-v2-normalization` |
| S13 | `mark3-equal-work-control/benchmark_results/mark3_runtime_authority_v2/runtime_summary.md`; audit worktree `mark3-runtime-authority-audit-v2`; repair commit `c06555a` |
| S14 | `mark3-equal-work-control/benchmark_results/competition_contract_harness/harness_summary.md`; worktree `mark3-competition-harness-contract`; commit `3973785` |
| S15 | `mark3-equal-work-control/benchmark_results/mark3_equal_work_control/control_summary.md`; commit `33fa7c4` |
| S16 | `mark3-equal-work-control/benchmark_results/mark3_final_strength_gate_400/strength_gate_summary.md` |
| S17 | `deploy-build3-final/benchmark_results/final_build3_submission/final_submission_summary.md`; commit `fefaeb8` |
| S18 | This repository: [DEVLOG.md](DEVLOG.md), [REPORT.md](REPORT.md), [results](results/), and [snapshots](snapshots/) |
| S19 | `STARTER/benchmark_results/astra_v03_vs_build3/match_summary.md` and `extension_to_0700/match_summary.md` |

The scope was checked against folder creation dates: the original `stochastic-gambit` folder dates to September 4; the later sibling chess projects are `mark3-runtime-authority-audit-v2`, `mark3-competition-harness-contract`, `mark3-equal-work-control`, `deploy-build3-final`, and `chess-fr-fr`. Unrelated earlier Python projects were excluded. The final-submission identification, personal challenge, and competition placing are supplied by the project author.
