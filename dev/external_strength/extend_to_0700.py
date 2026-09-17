"""User-authorized time extension; the original 40-game runner stays unchanged.

Wait for its successful completion and process exit, then use unused eligible
openings first and only then marked repeats, in complete colour-swapped pairs.
No new pair starts at/after 07:00 BST. No engine
development, uploads, score-dependent stopping, or changes to the first test.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import threading
import time
import traceback

import chess
import chess.pgn
import run_match as match

ORIGINAL = match.OUTPUT
EXTENSION = ORIGINAL / "extension_to_0700"
CUTOFF = datetime(2026, 9, 11, 7, 0, tzinfo=match.LONDON)


def extension_order(original_schedule):
    original_keys = {chess.Board(item["fen"])._transposition_key()
                     for item in original_schedule["openings"]}
    corpus = json.loads(match.CORPUS.read_text())
    eligible, unused, identities = [], [], set()
    for item in corpus["openings"]:
        board = chess.Board(item["fen"])
        if (not board.is_valid() or board.is_check() or board.outcome(claim_draw=True) is not None
                or item["category"] in ("tactical", "endgame", "defensive")
                or abs(match.material_balance(board)) > 100 or len(board.piece_map()) < 28):
            continue
        mate_in_one = False
        for move in list(board.legal_moves):
            board.push(move)
            mate_in_one |= board.is_checkmate()
            board.pop()
        if mate_in_one:
            continue
        key = board._transposition_key()
        if key in identities:
            continue
        identities.add(key)
        entry = {**item, "opening_id": item["name"],
                 "opening_plies": match.CONTRACT_MODULE.opening_plies_from_fen(item["fen"]),
                 "material_balance_cp": match.material_balance(board)}
        eligible.append(entry)
        if key not in original_keys:
            unused.append(entry)
    assert original_keys <= identities, "Selection filters changed relative to original"
    return unused, eligible


def original_process_exited(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=,command="],
                            capture_output=True, text=True)
    line = result.stdout.strip()
    return not line or line.startswith("Z") or str(match.HERE / "run_match.py") not in line


def main():
    original_preflight = json.loads((ORIGINAL / "preflight.json").read_text())
    original_schedule = json.loads((ORIGINAL / "schedule.json").read_text())
    original_start = json.loads((ORIGINAL / "RUN_STARTED.json").read_text())
    assert original_preflight["status"] == "passed"
    assert match.sha256(ORIGINAL / "schedule.json") == original_preflight["schedule_sha256"]
    match.check_hashes()
    match.verify_extractions(original_preflight)
    unused, eligible = extension_order(original_schedule)
    from extension_report import self_tests
    self_tests()
    assert not EXTENSION.exists(), "Extension namespace exists; refusing overwrite"
    EXTENSION.mkdir()
    for name in ("runtime_logs", "completed", "move_traces"):
        (EXTENSION / name).mkdir()
    match.OUTPUT = EXTENSION
    match.write_new(EXTENSION / "progress.log", "")
    frozen = {"authorized_at": match.stamp(), "cutoff": CUTOFF.isoformat(),
              "rule": "Do not start a pair at or after cutoff; finish any pair already started",
              "initial_clock_ms": 120000, "increment_ms": 500, "contract": "competition_600",
              "max_concurrent_games": 2, "concurrency_policy": "colour-swapped games of the same opening only",
              "original_schedule_sha256": original_preflight["schedule_sha256"],
              "unused_openings_first": unused, "repeat_cycle_order": eligible,
              "selection_filters": "Same original screen: valid live board, not in check, category not tactical/endgame/defensive, "
                  "material within one pawn, >=28 pieces, no mate in one; frozen corpus order, counter-free deduplication",
              "pair_generation": "For extension index i=0,1,...: first unused_openings_first[i], then "
                  "repeat_cycle_order[(i-len(unused_openings_first)) % len(repeat_cycle_order)]; "
                  "global pair 21+i; slots E{i+1:04d}A/B; A has Astra White, B Astra Black",
              "repeat_policy": "All qualifying unused openings precede any repeats; repeated games explicitly marked",
              "statistics_policy": "Repeated openings are not new independent coverage; cluster uncertainty by opening identity",
              "extra_games_launch_automatically": True}
    match.write_new(EXTENSION / "schedule.json", frozen)
    report = {**original_preflight, "extension_authorization": frozen,
              "original_preflight_file": str(ORIGINAL / "preflight.json"),
              "extension_schedule_sha256": match.sha256(EXTENSION / "schedule.json"),
              "extension_script_hashes": {name: match.sha256(match.HERE / name)
                  for name in ("extend_to_0700.py", "extension_report.py")},
              "status": "waiting_for_original_40", "pid": os.getpid()}
    match.write_new(EXTENSION / "preflight.json", report)
    caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
    assert caffeinate.poll() is None
    match.write_new(EXTENSION / "SUPERVISOR_STARTED.json", {"started_at": match.stamp(),
        "pid": os.getpid(), "caffeinate_pid": caffeinate.pid, "original_pid": original_start["pid"],
        "cutoff": CUTOFF.isoformat()})
    match.log("extension_armed", cutoff=CUTOFF.isoformat(), original_pid=original_start["pid"])
    monitor_done = threading.Event()
    monitor = None
    pair_records = []
    try:
        last_notice = 0
        while (not (ORIGINAL / "results.json").exists()
               or not (ORIGINAL / "match_summary.md").exists()
               or not original_process_exited(original_start["pid"])):
            if (ORIGINAL / "operational_failure.json").exists():
                raise match.HarnessFailure("Original 40 encountered an operational failure; extension not launched")
            if (original_process_exited(original_start["pid"])
                    and not (ORIGINAL / "match_summary.md").exists()):
                raise match.HarnessFailure("Original coordinator exited without completing its report")
            if time.monotonic() - last_notice >= 60:
                count = len((ORIGINAL / "games.jsonl").read_text().splitlines())
                match.log("waiting_for_original", completed_games=count)
                last_notice = time.monotonic()
            time.sleep(5)
        initial_results = json.loads((ORIGINAL / "results.json").read_text())
        assert initial_results["status"] == "complete" and initial_results["games"] == 40
        assert original_process_exited(original_start["pid"])
        preserved = {name: match.sha256(ORIGINAL / name) for name in
                     ("schedule.json", "progress.log", "games.jsonl", "games.pgn",
                      "results.json", "match_summary.md", "preflight.json")}
        match.write_new(EXTENSION / "primary_preservation.json", preserved)
        # The original process may be closing its own caffeinate after the report.
        for attempt in range(20):
            try:
                load_check = match.process_check()
                break
            except AssertionError:
                if attempt == 19:
                    raise
                time.sleep(1)
        match.check_hashes()
        match.verify_extractions(original_preflight)
        assert match.sha256(EXTENSION / "schedule.json") == report["extension_schedule_sha256"]
        assert {name: match.sha256(match.HERE / name) for name in report["extension_script_hashes"]} == report["extension_script_hashes"]
        assert {name: match.sha256(match.HERE / name) for name in original_preflight["runner_hashes"]} == original_preflight["runner_hashes"]
        match.write_new(EXTENSION / "launch_preflight.json", {"status": "passed", "at": match.stamp(),
            "process_check": load_check, "original_completed_games": 40,
            "hashes": match.check_hashes(), "extension_script_hashes": report["extension_script_hashes"],
            "original_coordinator_exited": True, "unused_eligible_openings": len(unused),
            "total_eligible_openings": len(eligible)})
        for filename in ("games.jsonl", "games.pgn", "started_pairs.jsonl"):
            match.write_new(EXTENSION / filename, "")
        monitor = threading.Thread(target=match.heartbeat, args=(monitor_done,), daemon=True)
        monitor.start()
        match.log("extension_started", cutoff=CUTOFF.isoformat())
        with ThreadPoolExecutor(max_workers=2) as pool:
            index = 0
            while datetime.now(match.LONDON) < CUTOFF:
                repeated = index >= len(unused)
                opening = eligible[(index - len(unused)) % len(eligible)] if repeated else unused[index]
                repeat_cycle = 1 + (index - len(unused)) // len(eligible) if repeated else 0
                slots = [{"slot": f"E{index + 1:04d}{suffix}", "pair": 21 + index,
                          "opening_id": opening["opening_id"], "fen": opening["fen"],
                          "opening_plies": opening["opening_plies"], "white": white, "black": black,
                          "astra_colour": "white" if white == "CAND" else "black",
                          "contract": "competition_600", "initial_clock_ms": 120000, "increment_ms": 500,
                          "repeat_opening": repeated, "repeat_cycle": repeat_cycle}
                         for suffix, white, black in (("A", "CAND", "BASE"), ("B", "BASE", "CAND"))]
                assert len(slots) == 2 and len({s["fen"] for s in slots}) == 1
                admitted = datetime.now(match.LONDON)
                if admitted >= CUTOFF:
                    break
                pair_start = time.perf_counter()
                planned = {"pair": 21 + index, "admitted_at": admitted.isoformat(),
                           "opening_id": slots[0]["opening_id"], "slots": slots}
                match.write_new(EXTENSION / "completed" / f"pair-{21 + index:04d}-schedule.json", planned)
                with (EXTENSION / "started_pairs.jsonl").open("a") as stream:
                    stream.write(json.dumps(planned) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                match.log("pair_started", pair=21 + index, opening=slots[0]["opening_id"],
                          repeat_opening=repeated, repeat_cycle=repeat_cycle, admitted_at=admitted.isoformat())
                barrier = threading.Barrier(2)
                futures = [pool.submit(match.play_slot, slot, original_preflight, barrier) for slot in slots]
                games = [future.result() for future in as_completed(futures)]
                pair_record = {"pair": 21 + index, "opening_id": slots[0]["opening_id"],
                               "wall_seconds": time.perf_counter() - pair_start,
                               "admitted_at": admitted.isoformat(), "completed_at": match.stamp(),
                               "slots": sorted(game["slot"] for game in games)}
                pair_records.append(pair_record)
                match.write_new(EXTENSION / "completed" / f"pair-{21 + index:04d}.json", pair_record)
                match.log("pair_completed", pair=21 + index,
                          extension_completed_games=len(pair_records) * 2,
                          total_completed_games=40 + len(pair_records) * 2,
                          wall_seconds=round(pair_record["wall_seconds"], 3))
                index += 1
        match.log("cutoff_reached", cutoff=CUTOFF.isoformat(), completed_extension_pairs=len(pair_records))
        from extension_report import finish_report
        finish_report(ORIGINAL, EXTENSION, original_preflight, original_schedule,
                      original_start, pair_records, report["extension_script_hashes"])
    except Exception:
        match.ABORT.set()
        failure = {"at": match.stamp(), "error": traceback.format_exc()}
        match.write_new(EXTENSION / "operational_failure.json", failure)
        match.log("operational_failure", error=failure["error"])
        raise
    finally:
        monitor_done.set()
        if monitor:
            monitor.join(timeout=2)
        if caffeinate.poll() is None:
            caffeinate.terminate()
            caffeinate.wait(timeout=2)


if __name__ == "__main__":
    main()
