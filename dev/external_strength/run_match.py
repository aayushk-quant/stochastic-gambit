"""Immutable-engine, pair-concurrent external strength test. No engine tuning.

Only this new run namespace receives outputs. Existing archives, engines, corpus
and audited harness are read-only. Final result files use exclusive creation;
completed games are fsynced immediately and also saved individually.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import selectors
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from zoneinfo import ZoneInfo

import chess
import chess.pgn

ROOT = Path("/Users/aayushkumar/Documents/PYTHON")
HERE = Path(__file__).resolve().parent
PYTHON = ROOT / "stochastic-gambit/aichessathon-starter/.venv/bin/python"
OUTPUT = ROOT / "stochastic-gambit/aichessathon-starter/benchmark_results/astra_v03_vs_build3"
CORPUS = ROOT / "stochastic-gambit/aichessathon-starter/benchmark_results/strength_gate_build3/openings.json"
CONTRACT_FILE = ROOT / "mark3-competition-harness-contract/harness/contract.py"
SOURCE = ROOT / "chess-fr-fr/submission/agent.py"
ARCHIVES = {"CAND": ROOT / "chess-fr-fr/dev/chessathon-submission.zip",
            "BASE": ROOT / "deploy-build3-final/submission_build3.zip"}
EXPECTED_SOURCE = "7a862a0c104ac76b5d2e7174f9cc31f7bdfe592a12c4dc125ca8b51ac470e279"
EXPECTED_ZIPS = {"CAND": "3f3f7cba8798a90d69a59e3e5ca7525b5dcf6c8ec829ccd4d6efbad37d2b2326",
                 "BASE": "ca4c81d7a28d979ae8284d07366f825bb0f6514ba2b75de1c562191747f6fef8"}
EXPECTED_CORPUS = "b6401ac22f7daa01c74fac563aec20bc95d3ceba96e364ed08f8413fc91e91d5"
EXPECTED_CONTRACT = "19388dfef216baa67ddad7397b8b00d72b59703438ae8634f73bd7d18e2413ce"
NAMES = {"CAND": "Astra clean-sheet V0.3", "BASE": "Frozen final Build3"}
BASE_MS, INCREMENT_MS, INIT_SECONDS = 120000, 500, 90.0
LONDON = ZoneInfo("Europe/London")
SELECTED = (
    "italian-giuoco-pianissimo", "qgd-classical", "kings-indian-classical",
    "ruy-lopez-closed", "caro-kann-classical", "english-symmetrical",
    "nimzo-indian-classical", "petroff-classical", "catalan-open",
    "french-advance", "kings-indian-cramped-black", "hedgehog",
    "kings-indian-mar-del-plata", "maroczy-bind", "carlsbad-structure",
    "isolated-queen-pawn", "benoni-imbalance", "greek-gift-setup",
    "kings-gambit-declined", "yugoslav-attack",
)
ABORT = threading.Event()
LOG_LOCK = threading.Lock()
STATUS_LOCK = threading.Lock()
LIVE_STATUS = {}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp():
    return datetime.now(LONDON).isoformat(timespec="seconds")


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def log(event, **fields):
    record = {"time": stamp(), "event": event, **fields}
    line = json.dumps(record, sort_keys=True)
    with LOG_LOCK:
        with (OUTPUT / "progress.log").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(line, flush=True)


def load_contract():
    assert sha256(CONTRACT_FILE) == EXPECTED_CONTRACT, "Audited contract changed"
    spec = importlib.util.spec_from_file_location("audited_competition_contract", CONTRACT_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    contract = module.get("competition_600")
    assert contract.max_total_plies == 600 and contract.count_opening_plies
    assert not contract.adjudicate_at_cap
    return module, contract


CONTRACT_MODULE, CONTRACT = load_contract()


class HarnessFailure(RuntimeError):
    pass


class EngineFailure(RuntimeError):
    def __init__(self, reason, detail=""):
        super().__init__(detail or reason)
        self.reason, self.detail = reason, detail


def check_hashes():
    result = {"source": sha256(SOURCE),
              "archives": {side: sha256(path) for side, path in ARCHIVES.items()},
              "corpus": sha256(CORPUS), "contract": sha256(CONTRACT_FILE)}
    assert result["source"] == EXPECTED_SOURCE, "Candidate source hash mismatch"
    assert result["archives"] == EXPECTED_ZIPS, "Archive hash mismatch"
    assert result["corpus"] == EXPECTED_CORPUS, "Frozen corpus changed"
    assert result["contract"] == EXPECTED_CONTRACT, "Audited contract changed"
    return result


def process_check():
    raw = subprocess.check_output(["ps", "-axo", "pid,ppid,%cpu,etime,command"], text=True)
    rows = []
    parents = {}
    for line in raw.splitlines()[1:]:
        fields = line.strip().split(None, 4)
        if len(fields) == 5:
            pid, ppid, cpu, elapsed, command = fields
            row = {"pid": int(pid), "ppid": int(ppid), "cpu_percent": float(cpu),
                   "elapsed": elapsed, "command": command}
            rows.append(row)
            parents[int(pid)] = int(ppid)
    ancestors = set()
    pid = os.getpid()
    while pid and pid not in ancestors:
        ancestors.add(pid)
        pid = parents.get(pid, 0)
    chess_processes = []
    for row in rows:
        command = row["command"].lower()
        executable = Path(command.split()[0]).name
        is_chess = ("stockfish" in executable or (
            "python" in executable and any(word in command for word in
            ("chess", "strength_gate", "benchmark", "selfplay", "self_play", "worker"))))
        if is_chess and row["pid"] not in ancestors:
            chess_processes.append(row)
    assert not chess_processes, f"Competing chess processes: {chess_processes}"
    return {"checked_at": stamp(), "competing_chess_processes": chess_processes,
            "other_high_cpu_processes": [r for r in rows if r["cpu_percent"] >= 50
                                         and r["pid"] not in ancestors]}


def extract_archive(side):
    directory = Path(tempfile.mkdtemp(prefix=f"astra-v03-vs-build3-{side.lower()}-"))
    members = {}
    with zipfile.ZipFile(ARCHIVES[side]) as archive:
        assert sum(info.file_size for info in archive.infolist()) < 50000000
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert (info.external_attr >> 16) & 0o170000 != 0o120000, "ZIP symlink"
            if info.is_dir():
                continue
            assert info.filename not in members, "Duplicate ZIP member"
            members[info.filename] = hashlib.sha256(archive.read(info)).hexdigest()
        assert "agent.py" in members
        archive.extractall(directory)
    for relative, digest in members.items():
        path = directory / relative
        assert sha256(path) == digest
        path.chmod(0o444)
    for child in sorted(directory.rglob("*"), reverse=True):
        if child.is_dir():
            child.chmod(0o555)
    directory.chmod(0o555)
    return {"root": str(directory.resolve()), "members": members,
            "archive": str(ARCHIVES[side]), "archive_sha256": EXPECTED_ZIPS[side]}


class Worker:
    def __init__(self, side, extraction, label):
        self.side = side
        self.extraction = extraction
        self.label = label
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer = b""
        self.stderr_stream = None
        self.ready = None
        self.last_response = {}
        self.error_detail = ""

    def start(self):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0",
                           OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                           MKL_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
        self.stderr_stream = (OUTPUT / "runtime_logs" / f"{self.label}-{self.side}.stderr").open("xb")
        self.process = subprocess.Popen(
            [str(PYTHON), "-I", "-B", "-u", str(HERE / "worker.py"), self.extraction["root"]],
            cwd=self.extraction["root"], env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.stderr_stream, bufsize=0,
            start_new_session=True,
        )
        os.set_blocking(self.process.stdout.fileno(), False)
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        started = time.perf_counter()
        try:
            ready = self._receive(INIT_SECONDS, limit=65536)
        finally:
            self._suspend()
        if ready.get("ready") is not True:
            raise EngineFailure("init", repr(ready))
        root = Path(self.extraction["root"])
        if (Path(ready.get("agent_file", "")).resolve() != root / "agent.py"
                or ready.get("sys_path_first") != str(root)
                or ready.get("parameters") != ["fen", "time_left_ms"]):
            raise HarnessFailure(f"Wrong agent origin or signature: {ready}")
        for relative, digest in ready["loaded_files"].items():
            if self.extraction["members"].get(relative) != digest:
                raise HarnessFailure(f"Loaded module outside authoritative archive: {relative}")
        if ready["loaded_files"].get("agent.py") != self.extraction["members"]["agent.py"]:
            raise HarnessFailure("Wrong loaded agent hash")
        ready["startup_wall_seconds"] = time.perf_counter() - started
        self.ready = ready
        return ready

    def _receive(self, seconds, limit=4096):
        deadline = time.perf_counter() + max(0, seconds)
        while b"\n" not in self.buffer:
            if ABORT.is_set():
                raise HarnessFailure("Operational abort requested")
            if len(self.buffer) >= limit:
                raise EngineFailure("illegal", "Protocol response exceeds byte cap")
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise EngineFailure("flag", "No response before watchdog deadline")
            if not self.selector.select(min(remaining, 0.25)):
                continue
            chunk = os.read(self.process.stdout.fileno(), limit + 1)
            if not chunk:
                raise EngineFailure("crash", f"Worker exited: {self.process.poll()}")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        if len(line) > limit:
            raise EngineFailure("illegal", "Protocol response exceeds byte cap")
        try:
            payload = json.loads(line)
        except (ValueError, UnicodeDecodeError) as error:
            raise EngineFailure("illegal", str(error)) from error
        if not isinstance(payload, dict):
            raise EngineFailure("illegal", "Non-object protocol response")
        return payload

    def _suspend(self):
        if self.process is not None and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGSTOP)
            except ProcessLookupError:
                pass

    def move(self, fen, time_left_ms):
        try:
            os.killpg(self.process.pid, signal.SIGCONT)
            request = json.dumps({"fen": fen, "time_left_ms": time_left_ms}).encode() + b"\n"
            self.process.stdin.write(request)
            response = self._receive(time_left_ms / 1000 + 0.5)
            self.last_response = response
            if "exception" in response:
                raise EngineFailure("crash", json.dumps(response))
            if not isinstance(response.get("move"), str):
                raise EngineFailure("illegal", repr(response))
            return response["move"]
        except (BrokenPipeError, ProcessLookupError) as error:
            raise EngineFailure("crash", str(error)) from error
        finally:
            self._suspend()

    def stop(self):
        process = self.process
        if process is not None:
            if process.poll() is None:
                for sig in (signal.SIGCONT, signal.SIGTERM):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
            self.process = None
        self.selector.close()
        if self.stderr_stream is not None:
            self.stderr_stream.close()


def material_balance(board):
    return sum(value * (len(board.pieces(piece, chess.WHITE)) - len(board.pieces(piece, chess.BLACK)))
               for piece, value in ((1, 100), (2, 320), (3, 330), (4, 500), (5, 900)))


def make_schedule():
    corpus = json.loads(CORPUS.read_text())
    entries = {entry["name"]: entry for entry in corpus["openings"]}
    assert len(entries) == len(corpus["openings"])
    openings, games, identities = [], [], set()
    for pair, name in enumerate(SELECTED, 1):
        entry = dict(entries[name])
        board = chess.Board(entry["fen"])
        assert board.is_valid() and not board.is_check() and board.outcome(claim_draw=True) is None
        assert entry["category"] not in ("tactical", "endgame", "defensive")
        assert abs(material_balance(board)) <= 100 and len(board.piece_map()) >= 28
        for move in list(board.legal_moves):
            board.push(move)
            assert not board.is_checkmate(), f"Mate-in-one opening: {name}"
            board.pop()
        key = board._transposition_key()
        assert key not in identities
        identities.add(key)
        entry.update(opening_id=name, opening_plies=CONTRACT_MODULE.opening_plies_from_fen(entry["fen"]),
                     material_balance_cp=material_balance(board), pair=pair)
        CONTRACT.validate_opening(entry["opening_plies"])
        openings.append(entry)
        for suffix, white, black in (("A", "CAND", "BASE"), ("B", "BASE", "CAND")):
            games.append({"slot": f"{pair:02d}{suffix}", "pair": pair,
                          "opening_id": name, "fen": entry["fen"],
                          "opening_plies": entry["opening_plies"],
                          "white": white, "black": black,
                          "astra_colour": "white" if white == "CAND" else "black",
                          "contract": CONTRACT.name, "initial_clock_ms": BASE_MS,
                          "increment_ms": INCREMENT_MS})
    assert len(openings) == 20 and len(games) == 40 and len(identities) == 20
    assert Counter(game["astra_colour"] for game in games) == {"white": 20, "black": 20}
    return {"frozen_at": stamp(), "contract": asdict(CONTRACT),
            "initial_clock_ms": BASE_MS, "increment_ms": INCREMENT_MS,
            "max_concurrent_games": 2, "concurrency_policy": "same-opening colour-swapped pair only",
            "corpus_file": str(CORPUS), "corpus_sha256": EXPECTED_CORPUS,
            "selection_policy": "All 9 quiet, 4 cramped, 3 positional openings; balanced Benoni; "
                "three conventional same-side/uncommitted-castling opening setups. No engine evaluations "
                "or match results used. All within one pawn material, >=28 pieces, no check or mate in one.",
            "openings": openings, "games": games}


def run_loop(agents, slot, event=None, now=time.perf_counter):
    board = chess.Board(slot["fen"])
    opening_plies = slot["opening_plies"]
    CONTRACT.validate_opening(opening_plies)
    clocks = {chess.WHITE: float(slot["initial_clock_ms"]), chess.BLACK: float(slot["initial_clock_ms"])}
    increments = {chess.WHITE: 0, chess.BLACK: 0}
    elapsed_by_colour = {chess.WHITE: 0.0, chess.BLACK: 0.0}
    diagnostics = {}
    started = now()
    failure_colour, failure_detail = None, None
    while True:
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            result, termination = outcome.result(), outcome.termination.name.lower()
            break
        if CONTRACT.cap_reached(opening_plies, len(board.move_stack)):
            result, termination = "1/2-1/2", CONTRACT.cap_termination
            break
        colour = board.turn
        before = now()
        failure = None
        uci = None
        try:
            uci = agents[colour].move(board.fen(), int(clocks[colour]))
        except EngineFailure as error:
            failure = error
        elapsed = (now() - before) * 1000
        clocks[colour] -= elapsed
        elapsed_by_colour[colour] += elapsed
        colour_name = "white" if colour else "black"
        move_record = {"engine_ply": len(board.move_stack) + 1, "colour": colour_name,
                       "fen_before": board.fen(), "uci": uci, "elapsed_ms": elapsed,
                       "clock_after_think_ms": clocks[colour]}
        if failure is not None or clocks[colour] < 0:
            termination = "flag" if clocks[colour] < 0 or (failure and failure.reason == "flag") else failure.reason
            result = "0-1" if colour else "1-0"
            failure_colour = colour_name
            failure_detail = failure.detail if failure else "Elapsed time exceeded remaining clock"
            move_record.update(legal=False, failure=termination, increment_granted=False)
            if event:
                event(move_record)
            break
        try:
            move = chess.Move.from_uci(uci)
        except (ValueError, TypeError):
            move = None
        if move is None or move not in board.legal_moves:
            result, termination = ("0-1" if colour else "1-0"), "illegal"
            failure_colour, failure_detail = colour_name, f"Illegal UCI: {uci!r}"
            move_record.update(legal=False, failure=termination, increment_granted=False)
            if event:
                event(move_record)
            break
        board.push(move)
        clocks[colour] += slot["increment_ms"]
        increments[colour] += 1
        response = getattr(agents[colour], "last_response", {})
        if "internally_caught_exceptions" in response:
            diagnostics[colour_name] = response["internally_caught_exceptions"]
        move_record.update(legal=True, increment_granted=True,
                           clock_after_increment_ms=clocks[colour], fen_after=board.fen())
        if event:
            event(move_record)
    record = dict(slot)
    record.update(result=result, termination=termination, engine_plies=len(board.move_stack),
                  total_plies=CONTRACT.total_plies(opening_plies, len(board.move_stack)),
                  final_fen=board.fen(), final_clocks_ms={"white": clocks[True], "black": clocks[False]},
                  flag=termination == "flag", illegal=termination == "illegal",
                  crash=termination == "crash", failure_colour=failure_colour,
                  failure_detail=failure_detail, wall_seconds=now() - started,
                  legal_moves_by_colour={"white": increments[True], "black": increments[False]},
                  thinking_ms_by_colour={"white": elapsed_by_colour[True], "black": elapsed_by_colour[False]},
                  internally_caught_exceptions=diagnostics)
    game = chess.pgn.Game.from_board(board)
    game.headers.update(Event="Astra V0.3 vs frozen final Build3", Site="Local isolated-process external test",
                        Date=datetime.now(LONDON).strftime("%Y.%m.%d"), Round=slot["slot"],
                        White=NAMES[slot["white"]], Black=NAMES[slot["black"]], Result=result,
                        Termination=termination, Contract=CONTRACT.name,
                        TimeControl="120+0.5", OpeningId=slot["opening_id"],
                        OpeningPlies=str(opening_plies), EnginePlies=str(len(board.move_stack)),
                        TotalPlies=str(record["total_plies"]))
    return record, str(game) + "\n\n"


def verify_extractions(preflight):
    for side, extraction in preflight["extractions"].items():
        root = Path(extraction["root"])
        actual = {path.relative_to(root).as_posix(): sha256(path) for path in root.rglob("*") if path.is_file()}
        assert actual == extraction["members"], f"Extracted {side} package changed"


def preflight():
    hashes = check_hashes()
    assert sys.version_info[:2] == (3, 12)
    assert not OUTPUT.exists(), "Output namespace already exists; refusing overwrite"
    processes = process_check()
    schedule = make_schedule()
    OUTPUT.mkdir()
    (OUTPUT / "runtime_logs").mkdir()
    (OUTPUT / "completed").mkdir()
    (OUTPUT / "move_traces").mkdir()
    write_new(OUTPUT / "progress.log", "")
    write_new(OUTPUT / "schedule.json", schedule)
    write_new(OUTPUT / "corpus_snapshot.json", json.loads(CORPUS.read_text()))
    report = {"started_at": stamp(), "hashes": hashes, "process_check": processes,
              "identities": NAMES, "python_executable": str(PYTHON),
              "python_version": sys.version, "python_chess_version": chess.__version__,
              "contract": asdict(CONTRACT), "initial_clock_ms": BASE_MS, "increment_ms": INCREMENT_MS,
              "initialization_budget_seconds": INIT_SECONDS,
              "draw_policy": "Audited referee semantics: Board.outcome(claim_draw=True); history begins at supplied FEN",
              "pondering": "Workers SIGSTOP between calls, SIGCONT only for their own timed call",
              "worker_isolation": "fresh -I Python subprocess per engine per game; archive root first on sys.path",
              "build3_reconciliation": {
                  "authoritative_archive_sha256": EXPECTED_ZIPS["BASE"],
                  "strength_parent_commit": "1ede533f169229d0c0ae3d30f23fc89328ee8f82",
                  "final_deployment_commit": "fefaeb8666947f13b962485b220566c9a2b72196",
                  "parent_config_git_blob": "a6ac0bf8fd0e4be83f1b831bf8b2207133308a1d",
                  "deployment_config_git_blob": "2aad474dedce1b00006cb6224c68b9358aad6bc2",
                  "user_confirmed_expected_change": "engine/config.py: log_search True to False",
                  "other_shipped_engine_modules_match_parent": True,
                  "zip_is_authoritative": True},
              "audited_harness_reuse": {"contract_file": str(CONTRACT_FILE), "sha256": EXPECTED_CONTRACT,
                  "checkout_commit": "3973785b24c64b7ba3904bc033773f0ff296aea9",
                  "note": "Original subprocess referee omits contract/clock metadata on ordinary endings. "
                      "Separate tested runner uses the unchanged audited contract and same adjudication/clock semantics; "
                      "no existing harness or engine files modified."},
              "selection_policy": schedule["selection_policy"], "games": 40, "pairs": 20,
              "unique_openings": 20, "max_concurrent_games": 2,
              "extractions": {}, "smoke_tests": {},
              "runner_hashes": {name: sha256(HERE / name) for name in ("run_match.py", "worker.py", "test_runner.py")}}
    try:
        from test_runner import run_tests
        report["harness_self_tests"] = run_tests()
        for side in ("CAND", "BASE"):
            extraction = extract_archive(side)
            report["extractions"][side] = extraction
            worker = Worker(side, extraction, "preflight")
            try:
                ready = worker.start()
                board = chess.Board()
                started = time.perf_counter()
                uci = worker.move(board.fen(), BASE_MS)
                elapsed = time.perf_counter() - started
                assert chess.Move.from_uci(uci) in board.legal_moves
                assert elapsed * 1000 < BASE_MS
                report["smoke_tests"][side] = {"ready": ready, "uci": uci,
                    "legal": True, "clock_ms": BASE_MS, "wall_seconds": elapsed}
            finally:
                worker.stop()
        verify_extractions(report)
        assert report["extractions"]["CAND"]["members"]["agent.py"] == EXPECTED_SOURCE
        report.update(status="passed", finished_at=stamp(), schedule_sha256=sha256(OUTPUT / "schedule.json"))
        write_new(OUTPUT / "preflight.json", report)
        log("preflight_passed", games=40, pairs=20, contract=CONTRACT.name)
    except Exception:
        report.update(status="failed", finished_at=stamp(), error=traceback.format_exc())
        write_new(OUTPUT / "preflight.json", report)
        log("preflight_failed", error=report["error"])
        raise


def play_slot(slot, preflight, barrier):
    workers = {colour: Worker(slot["white" if colour else "black"],
                              preflight["extractions"][slot["white" if colour else "black"]], slot["slot"])
               for colour in (True, False)}
    startup = time.perf_counter()
    init_failures = {}
    try:
        for colour, worker in workers.items():
            try:
                worker.start()
            except EngineFailure as error:
                init_failures["white" if colour else "black"] = {"reason": error.reason, "detail": error.detail}
        barrier.wait(timeout=2 * INIT_SECONDS + 30)
        if init_failures:
            raise HarnessFailure(f"Post-preflight initialization failed; no game started: {init_failures}")
        with (OUTPUT / "move_traces" / f"{slot['slot']}.jsonl").open("x") as stream:
            def event(record):
                stream.write(json.dumps(record) + "\n")
                stream.flush()
                with STATUS_LOCK:
                    LIVE_STATUS[slot["slot"]] = {"engine_ply": record["engine_ply"],
                        "last_move": record["uci"], "last_colour": record["colour"],
                        "clock_ms": round(record.get("clock_after_increment_ms", record["clock_after_think_ms"]), 1)}
            record, pgn = run_loop(workers, slot, event)
        record.update(completed_at=stamp(), engine_identities=NAMES, archive_hashes=EXPECTED_ZIPS,
                      candidate_source_sha256=EXPECTED_SOURCE,
                      worker_origins={"white" if colour else "black": worker.ready for colour, worker in workers.items()},
                      wall_including_startup_seconds=time.perf_counter() - startup)
        write_new(OUTPUT / "completed" / f"{slot['slot']}.json", record)
        write_new(OUTPUT / "completed" / f"{slot['slot']}.pgn", pgn)
        with LOG_LOCK:
            for filename, line in (("games.jsonl", json.dumps(record) + "\n"), ("games.pgn", pgn)):
                with (OUTPUT / filename).open("a") as stream:
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
        log("game_completed", slot=slot["slot"], opening=slot["opening_id"],
            result=record["result"], termination=record["termination"],
            astra_colour=slot["astra_colour"], total_plies=record["total_plies"],
            wall_seconds=round(record["wall_seconds"], 3))
        return record
    except Exception:
        ABORT.set()
        barrier.abort()
        raise
    finally:
        for worker in workers.values():
            worker.stop()
        with STATUS_LOCK:
            LIVE_STATUS.pop(slot["slot"], None)


def heartbeat(done):
    while not done.wait(30):
        with STATUS_LOCK:
            status = dict(LIVE_STATUS)
        log("heartbeat", games=status)


def run():
    preflight = json.loads((OUTPUT / "preflight.json").read_text())
    assert preflight["status"] == "passed"
    assert preflight["schedule_sha256"] == sha256(OUTPUT / "schedule.json")
    check_hashes()
    verify_extractions(preflight)
    assert {name: sha256(HERE / name) for name in preflight["runner_hashes"]} == preflight["runner_hashes"]
    processes = process_check()
    schedule = json.loads((OUTPUT / "schedule.json").read_text())
    assert len(schedule["games"]) == 40
    for filename in ("games.jsonl", "games.pgn", "results.json", "match_summary.md", "RUN_STARTED.json"):
        assert not (OUTPUT / filename).exists(), f"Refusing overwrite: {filename}"
    started = time.perf_counter()
    caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
    assert caffeinate.poll() is None, "caffeinate did not start"
    start_record = {"started_at": stamp(), "pid": os.getpid(), "parent_pid": os.getppid(),
                    "caffeinate_pid": caffeinate.pid, "caffeinate_command": ["caffeinate", "-i", "-w", str(os.getpid())],
                    "process_check": processes, "schedule_sha256": preflight["schedule_sha256"]}
    write_new(OUTPUT / "RUN_STARTED.json", start_record)
    write_new(OUTPUT / "games.jsonl", "")
    write_new(OUTPUT / "games.pgn", "")
    done = threading.Event()
    monitor = threading.Thread(target=heartbeat, args=(done,), daemon=True)
    monitor.start()
    pair_records = []
    log("match_started", games=40, pairs=20, contract=CONTRACT.name, initial_clock_ms=BASE_MS, increment_ms=INCREMENT_MS)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for pair in range(1, 21):
                slots = [game for game in schedule["games"] if game["pair"] == pair]
                assert len(slots) == 2 and {game["astra_colour"] for game in slots} == {"white", "black"}
                assert len({game["opening_id"] for game in slots}) == 1
                pair_start = time.perf_counter()
                log("pair_started", pair=pair, opening=slots[0]["opening_id"])
                barrier = threading.Barrier(2)
                futures = [pool.submit(play_slot, slot, preflight, barrier) for slot in slots]
                records = [future.result() for future in as_completed(futures)]
                duration = time.perf_counter() - pair_start
                pair_record = {"pair": pair, "opening_id": slots[0]["opening_id"],
                               "wall_seconds": duration, "slots": sorted(r["slot"] for r in records)}
                pair_records.append(pair_record)
                write_new(OUTPUT / "completed" / f"pair-{pair:02d}.json", pair_record)
                log("pair_completed", pair=pair, wall_seconds=round(duration, 3), completed_games=pair * 2)
        elapsed = time.perf_counter() - started
        finish_report(preflight, schedule, pair_records, elapsed, start_record)
    except Exception:
        ABORT.set()
        failure = {"time": stamp(), "error": traceback.format_exc(), "completed_pairs": pair_records}
        write_new(OUTPUT / "operational_failure.json", failure)
        log("operational_failure", error=failure["error"])
        raise
    finally:
        done.set()
        monitor.join(timeout=2)
        if caffeinate.poll() is None:
            caffeinate.terminate()
            caffeinate.wait(timeout=2)


def finish_report(preflight, schedule, pair_records, elapsed, start_record):
    records = [json.loads(line) for line in (OUTPUT / "games.jsonl").read_text().splitlines()]
    expected = {slot["slot"]: slot for slot in schedule["games"]}
    assert len(records) == 40 and Counter(r["slot"] for r in records) == Counter(expected.keys())
    assert Counter(r["pair"] for r in records) == {pair: 2 for pair in range(1, 21)}
    assert len({r["opening_id"] for r in records}) == 20
    assert Counter(r["astra_colour"] for r in records) == {"white": 20, "black": 20}
    wins = draws = losses = 0
    scores, pairs, terminations = [], {}, Counter()
    flags, illegals, crashes = Counter(), Counter(), Counter()
    final_clocks = {"CAND": [], "BASE": []}
    caught = {"CAND": [], "BASE": []}
    all_pids = []
    for record in records:
        slot = expected[record["slot"]]
        assert all(record[key] == value for key, value in slot.items())
        assert record["contract"] == "competition_600"
        assert record["initial_clock_ms"] == BASE_MS and record["increment_ms"] == INCREMENT_MS
        assert record["total_plies"] == record["opening_plies"] + record["engine_plies"] <= 600
        assert record["opening_plies"] == CONTRACT_MODULE.opening_plies_from_fen(record["fen"])
        board = chess.Board(record["fen"])
        pgn = chess.pgn.read_game(io.StringIO((OUTPUT / "completed" / f"{record['slot']}.pgn").read_text()))
        assert pgn is not None and not pgn.errors
        moves = list(pgn.mainline_moves())
        assert len(moves) == record["engine_plies"]
        for move in moves:
            assert move in board.legal_moves
            board.push(move)
        assert board.fen() == record["final_fen"]
        if record["termination"] == "ply_cap_draw":
            assert record["total_plies"] == 600 and record["result"] == "1/2-1/2"
            assert board.outcome(claim_draw=True) is None
        elif record["termination"] not in ("flag", "illegal", "crash"):
            outcome = board.outcome(claim_draw=True)
            assert outcome is not None and outcome.result() == record["result"]
            assert outcome.termination.name.lower() == record["termination"]
        for colour in ("white", "black"):
            side = record[colour]
            expected_clock = BASE_MS + record["legal_moves_by_colour"][colour] * INCREMENT_MS - record["thinking_ms_by_colour"][colour]
            assert abs(expected_clock - record["final_clocks_ms"][colour]) < 0.001
            final_clocks[side].append(record["final_clocks_ms"][colour])
            ready = record["worker_origins"][colour]
            assert ready["root"] == preflight["extractions"][side]["root"]
            assert ready["loaded_files"]["agent.py"] == preflight["extractions"][side]["members"]["agent.py"]
            all_pids.append(ready["pid"])
            if colour in record["internally_caught_exceptions"]:
                caught[side].append(record["internally_caught_exceptions"][colour])
        terminations[record["termination"]] += 1
        if record["failure_colour"]:
            side = record[record["failure_colour"]]
            flags[side] += record["flag"]
            illegals[side] += record["illegal"]
            crashes[side] += record["crash"]
        score = 0.5 if record["result"] == "1/2-1/2" else float((record["result"] == "1-0") == (record["astra_colour"] == "white"))
        scores.append(score)
        pairs.setdefault(record["pair"], []).append(score)
        wins += score == 1
        draws += score == 0.5
        losses += score == 0
    assert len(all_pids) == len(set(all_pids)) == 80, "Processes were reused across games"
    # Pair-level Student-t interval: opening pairs, not individual games, are the units.
    pair_means = [statistics.mean(pairs[pair]) for pair in sorted(pairs)]
    score = statistics.mean(scores)
    half_width = 2.093024054 * statistics.stdev(pair_means) / math.sqrt(20)
    # A conservative Wilson envelope using 20 independent opening pairs prevents
    # spurious zero-width intervals when all pairs have the same observed score.
    z, n = 1.95996398454, 20
    denominator = 1 + z * z / n
    center = (score + z * z / (2 * n)) / denominator
    wilson_half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / denominator
    lower = max(0.0, min(score - half_width, center - wilson_half))
    upper = min(1.0, max(score + half_width, center + wilson_half))
    def elo(value):
        if value <= 0:
            return "-infinity"
        if value >= 1:
            return "+infinity"
        return 400 * math.log10(value / (1 - value))
    if lower > 0.5:
        interpretation = "ASTRA CLEARLY BETTER"
    elif upper < 0.5:
        interpretation = "BUILD3 CLEARLY BETTER"
    elif abs(score - 0.5) <= 0.025:
        interpretation = "APPROXIMATELY LEVEL"
    elif score > 0.5:
        interpretation = "ASTRA NOMINALLY BETTER / INCONCLUSIVE"
    else:
        interpretation = "BUILD3 NOMINALLY BETTER / INCONCLUSIVE"
    # Default to the already hardware-validated baseline when superiority is inconclusive.
    recommendation = "ASTRA_READY_FOR_FINAL_VALIDATION" if lower > 0.5 and not (flags["CAND"] or illegals["CAND"] or crashes["CAND"] or sum(caught["CAND"])) else "KEEP_BUILD3"
    final_hashes = check_hashes()
    verify_extractions(preflight)
    assert sha256(OUTPUT / "schedule.json") == preflight["schedule_sha256"]
    assert {name: sha256(HERE / name) for name in preflight["runner_hashes"]} == preflight["runner_hashes"]
    sweeps = {"Astra": sum(sum(values) == 2 for values in pairs.values()),
              "split_or_drawn": sum(0 < sum(values) < 2 for values in pairs.values()),
              "Build3": sum(sum(values) == 0 for values in pairs.values())}
    report = {"status": "complete", "started_at": start_record["started_at"], "finished_at": stamp(),
              "games": 40, "complete_pairs": 20, "unique_openings": 20,
              "contract": CONTRACT.name, "initial_clock_ms": BASE_MS, "increment_ms": INCREMENT_MS,
              "astra_wdl": [wins, draws, losses], "build3_wdl": [losses, draws, wins],
              "astra_score_percent": score * 100, "pair_sweeps": sweeps,
              "rough_elo_difference_astra_minus_build3": elo(score),
              "uncertainty": {"label": "Conservative approximate 95% opening-pair interval (Student-t/Wilson envelope); descriptive, not certainty",
                  "score_percent": [100 * lower, 100 * upper], "elo_difference": [elo(lower), elo(upper)],
                  "independent_units": 20, "method": "Envelope of t(19)=2.093024054 times paired-score SE and Wilson with 20 independent opening pairs; fractional-pair Wilson is approximate"},
              "termination_counts": dict(terminations),
              "flags": {side: flags[side] for side in NAMES},
              "illegal_moves": {side: illegals[side] for side in NAMES},
              "crashes_or_uncaught_exceptions": {side: crashes[side] for side in NAMES},
              "internally_caught_exceptions_reported": {side: sum(caught[side]) if caught[side] else None for side in NAMES},
              "mean_remaining_clock_ms": {side: statistics.mean(values) for side, values in final_clocks.items()},
              "total_runtime_seconds": elapsed,
              "average_completed_pair_wall_seconds": statistics.mean(p["wall_seconds"] for p in pair_records),
              "pair_results": [{"pair": pair, "astra_points": sum(pairs[pair])} for pair in sorted(pairs)],
              "pair_timings": pair_records, "final_hashes": final_hashes,
              "verified_unique_worker_processes": len(set(all_pids)),
              "interpretation": interpretation, "recommendation": recommendation,
              "caution": "40 local games do not establish statistical certainty or performance on EPYC. No engine tuned or uploaded."}
    write_new(OUTPUT / "results.json", report)
    summary = "# Astra V0.3 vs frozen final Build3\n\n" + interpretation + "\n\n"
    summary += f"Astra W-D-L: {wins}-{draws}-{losses}; score {score:.1%}. Build3 W-D-L: {losses}-{draws}-{wins}.\n\n"
    summary += f"Pair sweeps Astra / split-or-drawn / Build3: {sweeps['Astra']} / {sweeps['split_or_drawn']} / {sweeps['Build3']}.\n\n"
    summary += f"Rough Elo difference (Astra minus Build3): {elo(score)}. Conservative approximate 95% pair-level score interval (Student-t/Wilson envelope): {lower:.1%}–{upper:.1%}; Elo interval {elo(lower)} to {elo(upper)}. Twenty opening pairs are a small sample; this is not statistical certainty.\n\n"
    summary += f"Terminations: {dict(terminations)}. Flags: {report['flags']}. Illegal moves: {report['illegal_moves']}. Crashes/uncaught exceptions: {report['crashes_or_uncaught_exceptions']}.\n\n"
    summary += f"Mean remaining clocks (ms): {report['mean_remaining_clock_ms']}. Runtime: {elapsed:.1f} seconds; average pair: {report['average_completed_pair_wall_seconds']:.1f} seconds.\n\n"
    summary += "Verified 40 unique slots, 20 complete colour-swapped pairs, 20 unique openings, 20 games per Astra colour, 80 fresh engine processes, competition_600 throughout, 120000+500 throughout, correct opening-ply accounting and unchanged archives/source. Each completed game was saved immediately. No uploads or engine changes occurred.\n\n"
    summary += recommendation + "\n"
    write_new(OUTPUT / "match_summary.md", summary)
    log("match_complete", astra_wdl=report["astra_wdl"], score_percent=score * 100,
        interpretation=interpretation, recommendation=recommendation, wall_seconds=round(elapsed, 3))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "run"))
    args = parser.parse_args()
    if args.phase == "preflight":
        preflight()
    else:
        run()


if __name__ == "__main__":
    main()
