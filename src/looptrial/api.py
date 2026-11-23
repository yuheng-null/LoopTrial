"""Public operations used by the CLI, MCP and local web workbench."""
import inspect
import json
import re
import socket
from http.client import HTTPConnection

from filelock import Timeout

from . import engine

METHODS = {"devices", "describe", "read_parameters", "apply_parameters", "run_experiment", "get_run",
           "cancel_run", "list_runs", "compare", "waveform", "review", "timeline"}
LIVE = {"connect", "disconnect", "snapshot", "plot_trace"}
ID = re.compile("[a-f0-9]{32}")


def descriptor():
    return engine.home() / "workbench.json"


def validate_remote_refs(name, args):
    fields = {"get_run": ["run_id"], "cancel_run": ["run_id"], "compare": ["first","second"],
              "waveform": ["run_id"], "plot_trace": ["run_id"], "review": ["record"]}
    for field in fields.get(name, []):
        if not ID.fullmatch(str(args.get(field, ""))):
            raise ValueError("Workbench operations require catalog run IDs")


def local(name, arguments, who):
    args = arguments.copy()
    token = engine.actor.set(who)
    try:
        if name == "parameter_history":
            return engine.writes(**args)
        if name in LIVE:
            if engine.runtime is None:
                raise engine.Problem("workbench_offline", "Start looptrial studio in this LOOPTRIAL_HOME first.")
            if name == "plot_trace":
                directory, record = engine.load_record(args["run_id"])
                rows = engine.records.load_samples(directory, record)
                stride = max(1, (len(rows) + 998) // 999)
                shown = rows[::stride]
                if rows and shown[-1] is not rows[-1]:
                    shown.append(rows[-1])
                return {"id":record["id"], "signals":record["signals"], "rows":shown, "total":len(rows)}
            return getattr(engine.runtime, name)(**args)
        if name not in METHODS:
            raise ValueError("Unknown LoopTrial operation")
        if name == "waveform":
            args["ref"] = args.pop("run_id")
        if name == "review":
            args["ref"] = args.pop("record")
        if engine.runtime is not None and name in ("describe", "read_parameters", "apply_parameters"):
            # Keep an endpoint open for the entire write/acknowledge/readback sequence.
            with engine.runtime.transition:
                return getattr(engine, name)(**args)
        return getattr(engine, name)(**args)
    finally:
        engine.actor.reset(token)


def call(name, args, who="cli"):
    path = descriptor()
    if not path.exists():
        return local(name, args, who)
    # Paths belong to the caller's machine and working directory. Portable review is local.
    if name in ("compare", "review", "waveform"):
        try:
            validate_remote_refs(name, args)
        except ValueError:
            return local(name, args, who)
    try:
        details = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return local(name, args, who)
    conn = HTTPConnection("127.0.0.1", details["port"], timeout=900)
    try:
        try:
            conn.connect()
        except (ConnectionRefusedError, socket.timeout):
            try:
                with engine.lock_for("workbench-owner"):
                    pass
            except Timeout as error:
                raise engine.Problem("workbench_unreachable", "Workbench is starting or unreachable.") from error
            return local(name, args, who)
        conn.request("POST", "/api/" + name, body=json.dumps(args).encode(),
                     headers={"Content-Type":"application/json", "Authorization":"Bearer " + details["token"],
                              "X-LoopTrial-Actor":who})
        response = conn.getresponse()
        result = json.loads(response.read())
        if response.status != 200:
            error = result.get("error", {})
            raise engine.Problem(error.pop("code", "workbench_error"), error.pop("message", "Request failed"), **error)
        return result
    finally:
        conn.close()


def from_engine(fn, args, who):
    """Map the existing callable signatures to their public names once."""
    if not descriptor().is_file():
        token = engine.actor.set(who)
        try:
            return fn(*args)
        finally:
            engine.actor.reset(token)
    name = fn.__name__
    fields = dict(inspect.signature(fn).bind(*args).arguments)
    if name == "writes":
        name = "parameter_history"
    elif name == "review":
        fields["record"] = fields.pop("ref")
    elif name == "waveform":
        fields["run_id"] = fields.pop("ref")
    return call(name, fields, who)
