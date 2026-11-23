"""Shared experiment service for the CLI and stdio MCP server."""

import contextlib
from contextvars import ContextVar, copy_context
import hashlib
import hmac
import importlib
from importlib.metadata import entry_points
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import threading
import uuid
from datetime import datetime, timezone

from filelock import FileLock, Timeout

from . import __version__, records


# Only the workbench process installs a runtime. Other clients use the public RPC.
runtime = None
actor = ContextVar("looptrial_actor", default="cli")


class Problem(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def failure(error):
    code = getattr(error, "code", None)
    if code is None:
        code = "invalid_input" if isinstance(error, (ValueError, TypeError, KeyError)) else "io_error"
    return {"ok": False, "error": {"code": code, "message": str(error), **getattr(error, "details", {})}}


OPERATION_ERRORS = (RuntimeError, ValueError, KeyError, OSError, TypeError, sqlite3.Error)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def publish_samples(uri, rows):
    """Optional observation of the same bounded acquisition, independent from recording."""
    if runtime is not None and rows:
        runtime.trial_samples(uri, rows)


def home():
    return Path(os.environ.get("LOOPTRIAL_HOME", Path.home() / ".looptrial")).expanduser().resolve()


@contextlib.contextmanager
def database():
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "catalog.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS config (uri TEXT PRIMARY KEY, params TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, key TEXT UNIQUE, resource TEXT NOT NULL,
                created TEXT NOT NULL, status TEXT NOT NULL, request TEXT NOT NULL,
                cancel INTEGER NOT NULL DEFAULT 0, summary TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS active_resource ON jobs(resource)
                WHERE status IN ('queued','running');
            CREATE TABLE IF NOT EXISTS writes (
                seq INTEGER PRIMARY KEY, resource TEXT NOT NULL, event TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS endpoints (uri TEXT PRIMARY KEY, alias TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS timeline (
                seq INTEGER PRIMARY KEY, uri TEXT NOT NULL, time TEXT NOT NULL,
                actor TEXT NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS timeline_endpoint ON timeline(uri,seq);
        """)
        with db:
            yield db
    finally:
        db.close()


def backend(uri):
    scheme, sep, endpoint = uri.partition("://")
    if not sep or not endpoint:
        raise ValueError("device URI must include scheme://endpoint; discover devices first")
    if scheme in ("serial", "ble"):
        if runtime is not None:
            board = runtime.board_for(uri)
            if board is not None:
                return board
        return importlib.import_module(".hardware", __package__)
    if scheme == "race":
        return importlib.import_module(".race", __package__)
    if scheme == "sim":
        return importlib.import_module(".models", __package__)
    matches = list(entry_points(group="looptrial.devices", name=scheme))
    if len(matches) != 1:
        raise ValueError(f"expected one installed adapter for scheme {scheme!r}, found {len(matches)}")
    return matches[0].load()


def source(uri):
    scheme = uri.partition("://")[0]
    return uri if scheme in ("sim", "race") else scheme + "://device"


def instance_alias(tag):
    """Link two transports within one lab without exporting the board's hardware identifier."""
    with database() as db:
        db.execute("INSERT OR IGNORE INTO local_settings VALUES ('alias_key',?)", (os.urandom(32).hex(),))
        key = bytes.fromhex(db.execute("SELECT value FROM local_settings WHERE name='alias_key'").fetchone()[0])
    return hmac.new(key, str(tag).encode(), "sha256").hexdigest()[:24]


def identify(adapter, uri):
    info = adapter.describe(uri)
    if "instance" in info:
        with database() as db:
            db.execute("INSERT OR REPLACE INTO endpoints VALUES (?,?)", (uri, info["instance"]))
    return info


def resource(uri):
    # The two bridge addresses can refer to the same target. Serialize physical I/O.
    return "board" if uri.startswith(("serial://", "ble://")) else uri


def lock_for(name, timeout=0):
    locks = home() / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    return FileLock(locks / (hashlib.sha256(name.encode()).hexdigest() + ".lock"), timeout=timeout)


@contextlib.contextmanager
def device_lock(uri, timeout=0):
    try:
        with lock_for("device/" + resource(uri), timeout=timeout):
            session = getattr(backend(uri), "session", None) if uri.startswith(("serial://", "ble://")) else None
            with session(uri) if session else contextlib.nullcontext():
                yield
    except Timeout as error:
        raise Problem("device_busy", "another process is using this device") from error


def devices():
    from serial.tools import list_ports

    return {"simulated": ["sim://thermal", "sim://sensor", "sim://motor", "sim://balance", "race://yali"],
            "serial_candidates": ["serial://" + port.device for port in list_ports.comports()],
            "ble": "ble://BD-BT26 (GATT discovery and firmware handshake on describe)",
            "adapter_schemes": sorted(e.name for e in entry_points(group="looptrial.devices")),
            "next": "describe a URI for identity, signals, parameter bounds and actions"}


def describe(uri):
    with device_lock(uri):
        return identify(backend(uri), uri)


def defaults(specs):
    return {k: spec["default"] for k, spec in specs.items() if "default" in spec}


def validate(values, specs):
    for name, value in values.items():
        if name not in specs:
            raise ValueError(f"unknown field {name!r}; available: {', '.join(specs)}")
        spec = specs[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} requires a finite number")
        if not spec.get("min", -math.inf) <= value <= spec.get("max", math.inf):
            raise ValueError(f"{name} outside declared range {spec.get('min')}..{spec.get('max')}")
        if spec.get("type") in ("integer", "int") and int(value) != value:
            raise ValueError(f"{name} requires an integer")


def _read(adapter, uri, info):
    if hasattr(adapter, "read"):
        return adapter.read(uri)
    with database() as db:
        row = db.execute("SELECT params FROM config WHERE uri=?", (uri,)).fetchone()
    return defaults(info["parameters"]) | (json.loads(row[0]) if row else {})


def _write(adapter, uri, values):
    if hasattr(adapter, "apply"):
        return adapter.apply(uri, values)
    with database() as db:
        db.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (uri, records.encode(values)))
    return values


def read_parameters(uri):
    with device_lock(uri):
        adapter = backend(uri)
        info = identify(adapter, uri)
        values = _read(adapter, uri, info)
        if runtime is not None:
            runtime.confirm(uri, values)
        return {"device": info["id"], "version": info["version"],
                "verified": values, "source": source(uri),
                **({"instance":info["instance"]} if "instance" in info else {})}


def _event(uri, event):
    with database() as db:
        db.execute("INSERT INTO writes(resource,event) VALUES (?,?)", (event.get("instance", uri), records.encode(event)))


def observe(uri, kind, details):
    stamp = now()
    with database() as db:
        seq = db.execute("INSERT INTO timeline(uri,time,actor,kind,details) VALUES(?,?,?,?,?)",
                         (uri, stamp, actor.get(), kind, records.encode(details))).lastrowid
    return {"seq": seq, "time": stamp, "actor": actor.get(), "kind": kind, "details": details}


def timeline(uri, limit=100):
    with database() as db:
        rows = db.execute("SELECT * FROM timeline WHERE uri=? ORDER BY seq DESC LIMIT ?",
                          (uri, bounded_limit(limit))).fetchall()
    return [{"seq": r["seq"], "time": r["time"], "actor": r["actor"], "kind": r["kind"],
             "details": json.loads(r["details"])} for r in reversed(rows)]


def apply_parameters(uri, values):
    if not values:
        raise ValueError("provide one or more parameter values")
    with device_lock(uri):
        check_idle(uri)
        adapter = backend(uri)
        info = identify(adapter, uri)
        validate(values, info["parameters"])
        before = _read(adapter, uri, info)
        target = before | values
        event = dict(time=now(), actor=actor.get(), device=info["id"], source=source(uri), before=before,
                     requested=values, persistence="temporary", state="write_attempted")
        if "instance" in info:
            event["instance"] = info["instance"]
        started = time.perf_counter()
        command_id = uuid.uuid4().hex
        event["command_id"] = command_id
        def stage(kind, fields):
            return observe(uri, kind, {"command_id": command_id, **fields})
        try:
            event["sent_at"] = stage("sent", {"requested": values})["time"]
            event["applied"] = _write(adapter, uri, target)
            event["applied_at"] = stage("applied", {"values": event["applied"]})["time"]
            event["verified"] = _read(adapter, uri, info)
            if event["verified"] != target:
                raise Problem("readback_mismatch", "effective values differ from requested configuration")
            event["state"] = "verified"
            event["confirm_ms"] = round((time.perf_counter() - started) * 1000, 3)
            event["verified_at"] = stage("verified", {"values": event["verified"], "confirm_ms": event["confirm_ms"]})["time"]
            if runtime is not None:
                runtime.confirm(uri, event["verified"], event["verified_at"])
        except Exception as error:
            event["error"] = failure(error)["error"]
            event["state"] = "unknown"
            try:
                _write(adapter, uri, before)
                event["last_readback"] = _read(adapter, uri, info)
                event["state"] = "restored" if event["last_readback"] == before else "restore_mismatch"
            except Exception as restore_error:
                event["restore_error"] = failure(restore_error)["error"]
            stage(event["state"], {"error": event["error"], "values": event.get("last_readback")})
            if runtime is not None:
                if event["state"] == "restored":
                    runtime.confirm(uri, before)
                else:
                    runtime.unknown(uri, "Effective settings could not be confirmed.")
            _event(uri, event)
            raise Problem(event["error"]["code"], str(error), receipt=event) from error
        _event(uri, event)
        return event


def writes(uri, limit=20):
    with database() as db:
        row = db.execute("SELECT alias FROM endpoints WHERE uri=?", (uri,)).fetchone()
        return [json.loads(r[0]) for r in db.execute(
            "SELECT event FROM writes WHERE resource=? ORDER BY seq DESC LIMIT ?", (row[0] if row else uri, bounded_limit(limit)))]


def _job(run_id):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise Problem("not_found", f"unknown run {run_id}")
    return row


def _summary(row):
    if row["summary"]:
        return json.loads(row["summary"])
    return dict(id=row["id"], status=row["status"], created=row["created"], cancel_requested=bool(row["cancel"]))


def get_run(run_id):
    row = _job(run_id)
    if row["status"] in ("queued", "running"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["created"])).total_seconds()
        if row["status"] == "running" or age > 120:
            try:
                with lock_for("worker/" + run_id):
                    row = _job(run_id)
                    if row["status"] in ("running", "queued"):
                        result = _finish_interrupted(row)
                        return result
            except Timeout:
                pass
    return _summary(row)


def _finish_interrupted(row):
    directory = home() / "runs" / row["id"]
    path = directory / "record.json"
    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
    else:
        directory.mkdir(parents=True, exist_ok=True)
        request = json.loads(row["request"])
        checkpoint = directory / "acquiring.json"
        record = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.is_file() else new_record(row, request)
        count, checksum = records.saved_samples(directory)
        record.update(status="failed", error={"code": "worker_lost", "message": "worker exited before closing this run"},
                      device_state={"state": "unknown", "last_confirmed": record.get("parameters")},
                      samples=count, samples_sha256=checksum, finished=now())
        records.write_json(path, record)
    return finish(record)


def check_idle(uri):
    with database() as db:
        row = db.execute("SELECT id FROM jobs WHERE resource=? AND status IN ('queued','running')",
                         (resource(uri),)).fetchone()
    if row and get_run(row[0])["status"] in ("queued", "running"):
        raise Problem("device_busy", "device has an active experiment", id=row[0])


def validate_rules(rules):
    for name, bounds in rules.items():
        if not name or not isinstance(bounds, dict) or not bounds or set(bounds) - {"le", "ge"}:
            raise ValueError("rules use {metric: {le: maximum, ge: minimum}}")
        for value in bounds.values():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("metric bounds must be finite numbers")


def verdict(checks):
    if not any(checks.values()):
        return None
    return all(check["passed"] for group in checks.values() for check in group)


def run_experiment(uri, action, conditions=None, goals=None, constraints=None, note="",
                   key=None, background=False, pace=0, fault=None):
    backend(uri)
    if not math.isfinite(pace) or not 0 <= pace <= 600:
        raise ValueError("pace must be 0..600 seconds")
    if (pace or fault) and not uri.startswith("sim://"):
        raise ValueError("pacing and fault injection require a simulator")
    if fault not in (None, "sample_gap"):
        raise ValueError("available fault: sample_gap")
    validate_rules(goals or {})
    validate_rules(constraints or {})
    request = dict(uri=uri, action=action, conditions=conditions or {}, goals=goals or {},
                   constraints=constraints or {}, note=note, pace=pace, fault=fault)
    payload = records.encode(request)
    if key is not None and not key.strip():
        raise ValueError("idempotency key cannot be blank")
    if key is not None:
        existing = keyed(key, payload)
        if existing:
            return existing
    run_id = uuid.uuid4().hex
    try:
        with lock_for("schedule/" + resource(uri), timeout=15):
            if key is not None:
                existing = keyed(key, payload)
                if existing:
                    return existing
            check_idle(uri)
            with database() as db:
                db.execute("INSERT INTO jobs(id,key,resource,created,status,request) VALUES(?,?,?,?,'queued',?)",
                           (run_id, key, resource(uri), now(), payload))
    except sqlite3.IntegrityError as error:
        existing = keyed(key, payload)
        if existing:
            return existing
        raise Problem("device_busy", "device has an active experiment") from error
    if background:
        if runtime is not None:
            context = copy_context()
            threading.Thread(target=context.run, args=(work, run_id), daemon=True).start()
            return get_run(run_id)
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            subprocess.Popen([sys.executable, "-m", "looptrial.worker", run_id], env=os.environ | {"LOOPTRIAL_HOME": str(home())},
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
        except OSError:
            _finish_interrupted(_job(run_id))
            raise
        return get_run(run_id)
    return work(run_id)


def keyed(key, payload):
    with database() as db:
        row = db.execute("SELECT id,request FROM jobs WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    if json.loads(row["request"]) != json.loads(payload):
        raise Problem("key_conflict", "key was already used for a different request", id=row["id"])
    return get_run(row["id"])


def new_record(row, request):
    return dict(format=1, looptrial=__version__, id=row["id"], created=row["created"],
                source=source(request["uri"]), **{k:v for k,v in request.items() if k != "uri"},
                device_state={"state": "unknown"}, metrics={}, checks={})


def finish(record):
    summary = {k:record[k] for k in ("id", "status", "source", "action", "conditions", "parameters",
               "device_state", "samples", "metrics", "checks", "passed", "error", "warnings", "instance",
               "actor", "last_parameter_write", "started", "finished", "device") if k in record}
    summary["record"] = "runs/" + record["id"] + "/record.json"
    with database() as db:
        db.execute("UPDATE jobs SET status=?,summary=? WHERE id=?",
                   (record["status"], records.encode(summary), record["id"]))
    return summary


def work(run_id):
    with lock_for("worker/" + run_id):
        row = _job(run_id)
        if row["status"] != "queued":
            return _summary(row)
        request = json.loads(row["request"])
        uri = request["uri"]
        directory = home() / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        with database() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (run_id,))
        record = new_record(row, request)
        rows = []
        last_check, last_cancel = 0.0, False

        def cancelled():
            nonlocal last_check, last_cancel
            if time.monotonic() - last_check > 0.05:
                last_cancel = bool(_job(run_id)["cancel"])
                last_check = time.monotonic()
            return last_cancel

        try:
            with device_lock(uri, timeout=90):
                adapter = backend(uri)
                info = identify(adapter, uri)
                record.update(device=info["id"], version=info["version"], object_source=info.get("source"),
                              signals=info["signals"], timestamp_unit="s")
                if "instance" in info:
                    record["instance"] = info["instance"]
                action = request["action"]
                if action not in info["actions"]:
                    raise ValueError(f"unknown action {action!r}; available: {', '.join(info['actions'])}")
                spec = info["actions"][action]
                declared = spec.get("metrics")
                if declared:
                    unknown = (request["goals"].keys() | request["constraints"].keys()) - declared.keys()
                    if unknown:
                        raise ValueError(f"unknown metrics for {action}: {', '.join(sorted(unknown))}")
                    record["metric_units"] = {k:s.get("unit") for k,s in declared.items()}
                    record["requires_event"] = {k:s["requires_event"] for k,s in declared.items() if "requires_event" in s}
                conditions = defaults(spec["conditions"]) | request["conditions"]
                validate(conditions, spec["conditions"])
                params = _read(adapter, uri, info)
                begin = observe(uri, "run_started", {"id": run_id, "action": action, "values": params})
                record.update(conditions=conditions, parameters=params, device_state={"state": "verified", "values": params},
                              actor=actor.get(), started=begin["time"], timeline_start=begin["seq"])
                with database() as db:
                    previous = db.execute("SELECT seq,time,actor,details FROM timeline WHERE uri=? AND kind='verified' AND seq<? ORDER BY seq DESC LIMIT 1",
                                          (uri, begin["seq"])).fetchone()
                if previous:
                    record["last_parameter_write"] = {"time": previous["time"], "actor": previous["actor"], **json.loads(previous["details"])}
                records.write_json(directory / "acquiring.json", record)
                until = time.monotonic() + request["pace"]
                while time.monotonic() < until:
                    if cancelled():
                        raise InterruptedError("cancelled before acquisition")
                    time.sleep(0.05)
                if cancelled():
                    raise InterruptedError("cancelled before acquisition")
                rows = adapter.acquire(uri, action, conditions, params, cancelled)
                if request["fault"] == "sample_gap":
                    rows = rows[:max(1, len(rows)//2)]
                    raise Problem("sample_gap", "injected sampling interruption; retained prefix of acquisition")
                records.check_rows(rows)
                metrics = adapter.metrics(uri, action, conditions, rows)
                if not all(math.isfinite(v) for v in metrics.values()):
                    raise ValueError("evaluator returned nonfinite metrics")
                record["metrics"] = metrics
                checks = {k: records.check_rules(metrics, request[k], record.get("requires_event")) for k in ("goals", "constraints")}
                record["checks"] = checks
                record["passed"] = verdict(checks)
                effective = _read(adapter, uri, info)
                record["device_state"] = {"state": "verified", "values": effective}
                if effective != params:
                    raise Problem("readback_mismatch", "effective configuration changed during acquisition", observed=effective)
                record["status"] = "completed"
        except Exception as error:
            record["status"] = "cancelled" if isinstance(error, InterruptedError) or getattr(error, "code", "") == "cancelled" else "failed"
            record["error"] = failure(error)["error"]
            if record["status"] == "cancelled":
                record["error"]["code"] = "cancelled"
            rows = getattr(error, "rows", None) or rows
            if not uri.startswith("sim://") and "observed" not in getattr(error, "details", {}):
                record["device_state"] = {"state": "unknown", "last_confirmed": record.get("parameters")}
                if not getattr(error, "state_unknown", True) and "parameters" in record:
                    try:
                        readback = read_parameters(uri)
                        if readback.get("instance") != record.get("instance") or readback["device"] != record["device"]:
                            raise Problem("wrong_device", "post-failure readback reached a different device")
                        record["device_state"] = {"state": "verified", "values": readback["verified"]}
                    except OPERATION_ERRORS as recovery_error:
                        record["device_state"]["recovery_error"] = failure(recovery_error)["error"]
            record.pop("passed", None)
        end = observe(uri, "run_" + record["status"], {"id": run_id, "state": record["device_state"], "error": record.get("error")})
        record.update(finished=end["time"], timeline_end=end["seq"], samples=len(rows), samples_sha256=records.write_samples(directory, rows))
        records.write_json(directory / "record.json", record)
        try:
            records.plot(directory, rows, record.get("signals", {}))
            (directory / "acquiring.json").unlink(missing_ok=True)
        except OPERATION_ERRORS as error:
            record["warnings"] = [{"code":"artifact_io", "message":str(error)}]
            records.write_json(directory / "record.json", record)
        return finish(record)


def cancel_run(run_id):
    with database() as db:
        db.execute("UPDATE jobs SET cancel=1 WHERE id=? AND status IN ('queued','running')", (run_id,))
    return get_run(run_id)


def bounded_limit(value):
    if not 1 <= value <= 200:
        raise ValueError("limit must be between 1 and 200")
    return value


def list_runs(limit=20):
    with database() as db:
        ids = [r[0] for r in db.execute("SELECT id FROM jobs ORDER BY rowid DESC LIMIT ?", (bounded_limit(limit),))]
    return [{k:v for k,v in get_run(i).items() if k in ("id", "source", "action", "status", "passed", "record")} for i in ids]


def load_record(ref):
    path = Path(ref)
    if len(ref) == 32 and all(c in "0123456789abcdef" for c in ref):
        path = home() / "runs" / ref
    if path.is_dir():
        path = path / "record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["format"] != 1:
        raise ValueError("unsupported record format")
    return path.parent, record


def review(ref):
    directory, record = load_record(ref)
    rows = records.load_samples(directory, record)
    result = dict(id=record["id"], status=record["status"], samples=len(rows), samples_sha256=record["samples_sha256"],
                  parameters=record.get("parameters"), device_state=record["device_state"])
    if record["status"] != "completed":
        return result | {"error": record.get("error"), "recomputed": False}
    records.check_rows(rows)
    adapter = (importlib.import_module(".hardware", __package__)
               if record["source"].startswith(("ble://", "serial://")) else backend(record["source"]))
    metrics = adapter.metrics(record["source"], record["action"], record["conditions"], rows)
    checks = {k:records.check_rules(metrics, record[k], record.get("requires_event")) for k in ("goals", "constraints")}
    if not matches_evaluation(record, metrics, checks):
        raise Problem("record_mismatch", "recomputed metrics or verdict differ from saved record", metrics=metrics)
    return result | {"recomputed": True, "metrics": metrics, "checks": checks, "passed": record["passed"]}


def matches_evaluation(record, metrics, checks):
    if metrics.keys() != record["metrics"].keys() or record["passed"] != verdict(checks):
        return False
    if any(not math.isclose(v, record["metrics"][k], rel_tol=1e-11, abs_tol=1e-12) for k,v in metrics.items()):
        return False
    # Compare saved rule values against saved metrics, allowing platform roundoff only in new metrics.
    expected = {group:records.check_rules(record["metrics"], record[group], record.get("requires_event")) for group in checks}
    return expected == record["checks"] and all(
        [c["passed"] for c in expected[group]] == [c["passed"] for c in checks[group]] for group in checks)


def waveform(ref, start=0, count=8):
    if start < 0 or not 1 <= count <= 200:
        raise ValueError("start must be nonnegative; count must be 1..200")
    directory, record = load_record(ref)
    rows = records.load_samples(directory, record)
    return dict(id=record["id"], start=start, total=len(rows), rows=rows[start:start+count])


def compare(first, second):
    a, b = (load_record(ref)[1] for ref in (first, second))
    for ref in (first, second):
        review(ref)
    differences = [k for k in ("device", "instance", "version", "action", "conditions") if a.get(k) != b.get(k)]
    if any(r["source"].startswith(("ble://", "serial://")) and not r.get("instance") for r in (a,b)):
        differences.append("unknown physical instance")
    if differences or any(r["status"] != "completed" for r in (a,b)):
        raise Problem("incomparable", "requires completed trials with matching identity, version, action and conditions", differences=differences)
    if a.get("action") == "lap" and any(r["metrics"].get("valid_lap") != 1 for r in (a,b)):
        raise Problem("incomparable", "An invalid lap has no finish time. Review its trajectory and stop event.")
    return dict(first=a["id"], second=b["id"], parameters=[a["parameters"], b["parameters"]],
                changed_parameters={k: [v,b["parameters"].get(k)] for k,v in a["parameters"].items() if b["parameters"].get(k) != v},
                last_parameter_writes=[a.get("last_parameter_write"), b.get("last_parameter_write")],
                delta={k:b["metrics"][k]-v for k,v in a["metrics"].items()})
