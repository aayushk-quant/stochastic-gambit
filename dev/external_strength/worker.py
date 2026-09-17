"""Isolated archive runner for the frozen Astra/Build3 external match.

No engine implementation is copied here. stdout redirection follows the audited
platform runner; ready metadata proves the origins of all loaded engine modules.
"""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import time
import traceback

protocol = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
root = Path(sys.argv[1]).resolve()
os.chdir(root)
sys.path.insert(0, str(root))
started = time.perf_counter()
agent = importlib.import_module("agent")
signature = inspect.signature(agent.get_move)
signature.bind("fen", 120000)
loaded = {}
for name, module in tuple(sys.modules.items()):
    if name == "agent" or name == "engine" or name.startswith("engine."):
        source = Path(module.__file__).resolve()
        relative = source.relative_to(root).as_posix()
        loaded[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
protocol.write(json.dumps({
    "ready": True, "pid": os.getpid(), "root": str(root),
    "agent_file": str(Path(agent.__file__).resolve()),
    "sys_path_first": sys.path[0], "python_executable": sys.executable,
    "python_version": sys.version, "signature": str(signature),
    "parameters": list(signature.parameters), "loaded_files": loaded,
    "import_seconds": time.perf_counter() - started,
}) + "\n")
protocol.flush()

for line in sys.stdin:
    request = json.loads(line)
    try:
        move = agent.get_move(request["fen"], request["time_left_ms"])
        if isinstance(move, str):
            response = {"move": move}
        else:
            response = {"invalid_return_type": type(move).__name__}
        state = getattr(agent, "_GAME", None)
        caught = getattr(state, "exceptions", None)
        if isinstance(caught, int):
            response["internally_caught_exceptions"] = caught
    except Exception as error:
        response = {"exception": type(error).__name__, "message": str(error)[:512],
                    "traceback": traceback.format_exc()[-2048:]}
    protocol.write(json.dumps(response) + "\n")
    protocol.flush()
