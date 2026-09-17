"""Separate extension audit/report. Original preregistered artifacts stay read-only."""
from collections import Counter, defaultdict
from datetime import datetime
import io
import json
import math
import statistics

import chess
import chess.pgn
import run_match as match


def astra_score(record):
    if record["result"] == "1/2-1/2":
        return 0.5
    return float((record["result"] == "1-0") == (record["astra_colour"] == "white"))


def elo(score):
    if score <= 0:
        return "-infinity"
    if score >= 1:
        return "+infinity"
    return 400 * math.log10(score / (1 - score))


def statistics_for(records):
    if not records:
        return {"games": 0, "complete_pairs": 0, "independent_opening_units": 0}
    units, pairs = defaultdict(list), defaultdict(list)
    wins = draws = losses = 0
    clocks, internal = defaultdict(list), defaultdict(list)
    terminations, flags, illegal, crashes = Counter(), Counter(), Counter(), Counter()
    for record in records:
        score = astra_score(record)
        units[record["opening_id"]].append(score)
        pairs[record["pair"]].append(score)
        wins += score == 1
        draws += score == 0.5
        losses += score == 0
        terminations[record["termination"]] += 1
        for colour in ("white", "black"):
            side = record[colour]
            clocks[side].append(record["final_clocks_ms"][colour])
            if colour in record.get("internally_caught_exceptions", {}):
                internal[side].append(record["internally_caught_exceptions"][colour])
        if record.get("failure_colour"):
            side = record[record["failure_colour"]]
            flags[side] += record["flag"]
            illegal[side] += record["illegal"]
            crashes[side] += record["crash"]
    assert all(len(values) == 2 for values in pairs.values())
    n, groups = len(records), len(units)
    mean = (wins + 0.5 * draws) / n
    residuals = [sum(values) - len(values) * mean for values in units.values()]
    standard_error = (math.sqrt(groups / (groups - 1) * sum(value * value for value in residuals)) / n
                      if groups > 1 else 0.0)
    t_half = 2.093024054 * standard_error
    z = 1.95996398454
    denominator = 1 + z * z / groups
    center = (mean + z * z / (2 * groups)) / denominator
    wilson_half = z * math.sqrt(mean * (1 - mean) / groups + z * z / (4 * groups * groups)) / denominator
    lower = max(0, min(mean - t_half, center - wilson_half))
    upper = min(1, max(mean + t_half, center + wilson_half))
    if lower > 0.5:
        interpretation = "ASTRA CLEARLY BETTER"
    elif upper < 0.5:
        interpretation = "BUILD3 CLEARLY BETTER"
    elif abs(mean - 0.5) <= 0.025:
        interpretation = "APPROXIMATELY LEVEL"
    elif mean > 0.5:
        interpretation = "ASTRA NOMINALLY BETTER / INCONCLUSIVE"
    else:
        interpretation = "BUILD3 NOMINALLY BETTER / INCONCLUSIVE"
    return {"games": n, "complete_pairs": len(pairs), "independent_opening_units": groups,
            "astra_wdl": [wins, draws, losses], "build3_wdl": [losses, draws, wins],
            "astra_score_percent": 100 * mean, "rough_elo_astra_minus_build3": elo(mean),
            "pair_sweeps": {"Astra": sum(sum(values) == 2 for values in pairs.values()),
                            "split_or_other_non_sweep": sum(0 < sum(values) < 2 for values in pairs.values()),
                            "Build3": sum(sum(values) == 0 for values in pairs.values())},
            "pair_astra_points_distribution": dict(Counter(str(sum(values)) for values in pairs.values())),
            "uncertainty": {"label": "Conservative approximate 95% opening-identity-clustered interval; not statistical certainty",
                "score_percent": [100 * lower, 100 * upper], "rough_elo": [elo(lower), elo(upper)],
                "independent_units": groups,
                "method": "Cluster-robust SE of game mean, clusters are opening IDs containing ALL repeats; "
                    "2.093024054 multiplier, enveloped by approximate Wilson using number of unique opening IDs. "
                    "Identical repetition of existing games cannot narrow this interval."},
            "opening_coverage": {name: {"games": len(values), "pairs": len(values) // 2,
                                        "astra_points": sum(values)} for name, values in sorted(units.items())},
            "repeat_games": sum(record.get("repeat_opening", False) for record in records),
            "termination_counts": dict(terminations),
            "flags": {side: flags[side] for side in match.NAMES},
            "illegal_moves": {side: illegal[side] for side in match.NAMES},
            "crashes_or_uncaught_exceptions": {side: crashes[side] for side in match.NAMES},
            "internally_caught_exceptions_reported": {side: sum(internal[side]) if internal[side] else None for side in match.NAMES},
            "mean_remaining_clock_ms": {side: statistics.mean(clocks[side]) for side in match.NAMES},
            "interpretation": interpretation}


def self_tests():
    records = []
    for index in range(20):
        for colour in ("white", "black"):
            records.append({"opening_id": f"opening-{index}", "pair": index,
                "astra_colour": colour, "white": "CAND" if colour == "white" else "BASE",
                "black": "BASE" if colour == "white" else "CAND",
                "result": ("1-0" if colour == "white" else "0-1") if index < 15 else "1/2-1/2",
                "termination": "checkmate", "final_clocks_ms": {"white": 1000, "black": 1000}})
    first = statistics_for(records)
    repeated = [dict(record, pair=record["pair"] + 20 * cycle, repeat_opening=cycle > 0)
                for cycle in range(5) for record in records]
    many = statistics_for(repeated)
    assert first["independent_opening_units"] == many["independent_opening_units"] == 20
    assert first["uncertainty"]["score_percent"] == many["uncertainty"]["score_percent"]
    assert many["repeat_games"] == 160
    assert statistics_for([])["games"] == 0


def audit_group(root, records, expected_slots, preflight):
    assert len(records) == len(expected_slots)
    assert Counter(record["slot"] for record in records) == Counter(expected_slots.keys())
    assert Counter(record["astra_colour"] for record in records) == Counter({"white": len(records) // 2, "black": len(records) // 2})
    launch_ids = []
    for record in records:
        assert all(record[key] == value for key, value in expected_slots[record["slot"]].items())
        assert record["contract"] == "competition_600"
        assert record["initial_clock_ms"] == 120000 and record["increment_ms"] == 500
        assert record["total_plies"] == record["opening_plies"] + record["engine_plies"] <= 600
        assert record["opening_plies"] == match.CONTRACT_MODULE.opening_plies_from_fen(record["fen"])
        board = chess.Board(record["fen"])
        game = chess.pgn.read_game(io.StringIO((root / "completed" / f"{record['slot']}.pgn").read_text()))
        assert game is not None and not game.errors and game.headers["Contract"] == "competition_600"
        assert game.headers["Result"] == record["result"]
        moves = list(game.mainline_moves())
        assert len(moves) == record["engine_plies"]
        for move in moves:
            assert move in board.legal_moves
            board.push(move)
        assert board.fen() == record["final_fen"]
        if record["termination"] == "ply_cap_draw":
            assert record["result"] == "1/2-1/2" and record["total_plies"] == 600
            assert board.outcome(claim_draw=True) is None
        elif record["termination"] not in ("flag", "illegal", "crash"):
            outcome = board.outcome(claim_draw=True)
            assert outcome is not None and outcome.result() == record["result"]
            assert outcome.termination.name.lower() == record["termination"]
        for colour in ("white", "black"):
            expected_clock = 120000 + 500 * record["legal_moves_by_colour"][colour] - record["thinking_ms_by_colour"][colour]
            assert abs(expected_clock - record["final_clocks_ms"][colour]) < 0.001
            side = record[colour]
            ready = record["worker_origins"][colour]
            extraction = preflight["extractions"][side]
            assert ready["root"] == extraction["root"]
            assert all(extraction["members"].get(name) == digest for name, digest in ready["loaded_files"].items())
            launch_ids.append((record["slot"], colour, ready["pid"]))
    assert len(launch_ids) == len(set(launch_ids)) == len(records) * 2
    with (root / "games.pgn").open() as stream:
        games = []
        while (game := chess.pgn.read_game(stream)) is not None:
            assert not game.errors
            games.append(game)
    assert len(games) == len(records)
    assert Counter(game.headers["Round"] for game in games) == Counter(expected_slots.keys())
    return {"validated_games": len(records), "fresh_worker_launches": len(launch_ids),
            "unique_os_pids": len({identity[2] for identity in launch_ids})}


def finish_report(original, extension, preflight, original_schedule, original_start,
                  pair_records, script_hashes):
    from extend_to_0700 import CUTOFF, extension_order
    assert {name: match.sha256(match.HERE / name) for name in script_hashes} == script_hashes
    extension_preflight = json.loads((extension / "preflight.json").read_text())
    assert match.sha256(extension / "schedule.json") == extension_preflight["extension_schedule_sha256"]
    assert {name: match.sha256(match.HERE / name) for name in preflight["runner_hashes"]} == preflight["runner_hashes"]
    preserved = json.loads((extension / "primary_preservation.json").read_text())
    assert {name: match.sha256(original / name) for name in preserved} == preserved
    match.check_hashes()
    match.verify_extractions(preflight)
    primary = [json.loads(line) for line in (original / "games.jsonl").read_text().splitlines()]
    extra = [json.loads(line) for line in (extension / "games.jsonl").read_text().splitlines()]
    started_pairs = [json.loads(line) for line in (extension / "started_pairs.jsonl").read_text().splitlines()]
    assert len(started_pairs) == len(pair_records)
    assert len(extra) == 2 * len(pair_records)
    frozen_order = json.loads((extension / "schedule.json").read_text())
    unused, eligible = extension_order(original_schedule)
    assert unused == frozen_order["unused_openings_first"]
    assert eligible == frozen_order["repeat_cycle_order"]
    expected_extra = {}
    for index, planned in enumerate(started_pairs):
        assert planned["pair"] == 21 + index
        assert datetime.fromisoformat(planned["admitted_at"]) < CUTOFF
        repeated = index >= len(unused)
        opening = eligible[(index - len(unused)) % len(eligible)] if repeated else unused[index]
        assert planned["opening_id"] == opening["opening_id"]
        assert len(planned["slots"]) == 2
        assert {slot["astra_colour"] for slot in planned["slots"]} == {"white", "black"}
        for slot in planned["slots"]:
            assert slot["fen"] == opening["fen"] and slot["repeat_opening"] == repeated
            assert slot["slot"] not in expected_extra
            expected_extra[slot["slot"]] = slot
    audits = {"primary": audit_group(original, primary, {slot["slot"]: slot for slot in original_schedule["games"]}, preflight),
              "extension": audit_group(extension, extra, expected_extra, preflight)}
    primary_stats = statistics_for(primary)
    extra_stats = statistics_for(extra)
    combined = statistics_for(primary + extra)
    primary_report = json.loads((original / "results.json").read_text())
    assert primary_stats["astra_wdl"] == primary_report["astra_wdl"]
    assert primary_stats["games"] == 40 and primary_stats["complete_pairs"] == 20
    assert combined["independent_opening_units"] == len({record["opening_id"] for record in primary + extra})
    candidate_failures = (combined["flags"]["CAND"] + combined["illegal_moves"]["CAND"]
                          + combined["crashes_or_uncaught_exceptions"]["CAND"]
                          + (combined["internally_caught_exceptions_reported"]["CAND"] or 0))
    # Primary remains the preregistered evidence. Repeats are descriptive support,
    # not a way to manufacture new independent opening coverage or significance.
    ready = (primary_stats["uncertainty"]["score_percent"][0] > 50
             and combined["uncertainty"]["score_percent"][0] > 50 and not candidate_failures)
    recommendation = "ASTRA_READY_FOR_FINAL_VALIDATION" if ready else "KEEP_BUILD3"
    finished = datetime.now(match.LONDON)
    total_runtime = (finished - datetime.fromisoformat(original_start["started_at"])).total_seconds()
    initial_pairs = primary_report["pair_timings"]
    all_pairs = initial_pairs + pair_records
    average_pair = statistics.mean(pair["wall_seconds"] for pair in all_pairs)
    metadata = {"status": "complete", "finished_at": finished.isoformat(),
                "cutoff": CUTOFF.isoformat(), "last_pair_admitted_at": pair_records[-1]["admitted_at"] if pair_records else None,
                "contract": "competition_600", "initial_clock_ms": 120000, "increment_ms": 500,
                "total_runtime_seconds_including_primary": total_runtime,
                "extension_pair_runtime_seconds": sum(pair["wall_seconds"] for pair in pair_records),
                "average_wall_seconds_per_completed_pair_combined": average_pair,
                "average_wall_seconds_per_completed_extension_pair": statistics.mean(pair["wall_seconds"] for pair in pair_records) if pair_records else None,
                "unused_eligible_openings_at_extension_start": [entry["opening_id"] for entry in unused],
                "unused_eligible_openings_actually_played": sorted({record["opening_id"] for record in extra if not record["repeat_opening"]}),
                "independent_units_policy": "All games and repeat pairs from one opening identity form ONE unit",
                "primary_artifacts_preserved": True, "primary_artifact_sha256": preserved,
                "engine_hashes_after": match.check_hashes(), "audits": audits,
                "caution": "Original 40 games are the primary preregistered test. Extension and combined scores are separate/descriptive. "
                    "Repeated deterministic openings add no new independent opening units. Local results do not prove EPYC performance or statistical certainty.",
                "recommendation": recommendation}
    match.write_new(extension / "results.json", {**metadata, "extension": extra_stats})
    match.write_new(extension / "combined_results.json", {**metadata, "primary_preregistered": primary_stats,
                                                         "extension": extra_stats, "combined_descriptive": combined,
                                                         "pair_timings": all_pairs})
    text = "# Frozen Astra V0.3 vs final Build3 — overnight extension\n\n"
    text += "The original 40-game test is primary and its artifacts are unchanged. The extension and combined totals are reported separately.\n\n"
    text += "| Dataset | Games | Pairs | Independent opening IDs | Astra W-D-L | Score |\n| --- | ---: | ---: | ---: | --- | ---: |\n"
    for name, stats in (("Primary preregistered", primary_stats), ("Extension", extra_stats), ("Combined descriptive", combined)):
        text += f"| {name} | {stats['games']} | {stats['complete_pairs']} | {stats['independent_opening_units']} | {stats.get('astra_wdl', [])} | {stats.get('astra_score_percent', 0):.2f}% |\n"
    text += f"\nPrimary interpretation: {primary_stats['interpretation']}. Combined descriptive interpretation: {combined['interpretation']}.\n\n"
    for name, stats in (("Primary", primary_stats), ("Extension", extra_stats), ("Combined", combined)):
        if not stats["games"]:
            continue
        text += f"{name}: Build3 W-D-L {stats['build3_wdl']}; pair sweeps {stats['pair_sweeps']}; rough Elo difference {stats['rough_elo_astra_minus_build3']}. "
        text += f"Conservative approximate 95% opening-identity-clustered score interval {stats['uncertainty']['score_percent']}; Elo interval {stats['uncertainty']['rough_elo']}.\n\n"
    text += f"The extension added {len(metadata['unused_eligible_openings_actually_played'])} new opening identities and {extra_stats.get('repeat_games', 0)} explicitly marked repeat games. "
    text += f"Combined uncertainty uses {combined['independent_opening_units']} opening units, NOT {combined['complete_pairs']} independent pairs. This is not statistical certainty.\n\n"
    text += f"Combined terminations: {combined['termination_counts']}. Flags: {combined['flags']}. Illegal moves: {combined['illegal_moves']}. Crashes/uncaught exceptions: {combined['crashes_or_uncaught_exceptions']}. "
    text += f"Internally caught exceptions where exposed: {combined['internally_caught_exceptions_reported']}.\n\n"
    text += f"Mean remaining clocks in ms: {combined['mean_remaining_clock_ms']}. Total wall time including primary: {total_runtime:.1f} seconds; average completed pair: {average_pair:.1f} seconds.\n\n"
    text += f"Finished {finished.isoformat()}. No pair was admitted at or after {CUTOFF.isoformat()}; an already-started pair was allowed to finish. "
    text += "All slots, colour swaps, opening accounting, legal PGN moves, clocks, archive origins and frozen source hashes were audited. No engines were changed or uploaded.\n\n"
    text += recommendation + "\n"
    match.write_new(extension / "match_summary.md", text)
    match.log("overnight_complete", primary_astra_wdl=primary_stats["astra_wdl"],
              extension_astra_wdl=extra_stats.get("astra_wdl"), combined_astra_wdl=combined["astra_wdl"],
              independent_opening_units=combined["independent_opening_units"], recommendation=recommendation)
