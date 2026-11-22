import asyncio
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from looptrial import engine


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPTRIAL_HOME", str(tmp_path / "home"))


def test_portable_review_tampering_and_comparison(tmp_path):
    first = engine.run_experiment("sim://thermal", "step", goals={"rise_s":{"le":50}})
    assert first["passed"] is False
    copied = tmp_path / "export"
    shutil.copytree(engine.home() / "runs" / first["id"], copied)
    assert engine.review(str(copied))["metrics"] == first["metrics"]
    engine.apply_parameters("sim://thermal", {"kp":.03})
    second = engine.run_experiment("sim://thermal", "step")
    measured_delta = second["metrics"]["rise_s"] - first["metrics"]["rise_s"]
    assert measured_delta != 0
    assert engine.compare(first["id"], second["id"])["delta"]["rise_s"] == measured_delta
    other = engine.run_experiment("sim://thermal", "step", conditions={"target_c":55})
    with pytest.raises(engine.Problem, match="matching"):
        engine.compare(first["id"], other["id"])
    with (copied / "samples.csv").open("a") as stream:
        stream.write("edited")
    with pytest.raises(ValueError, match="SHA"):
        engine.review(str(copied))


def test_cancel_leave_and_retry_same_key():
    def start(_):
        return engine.run_experiment("sim://thermal", "step", background=True, pace=10, key="retry")
    with ThreadPoolExecutor(2) as pool:
        first, retry = list(pool.map(start, range(2)))
    assert first["id"] == retry["id"]
    with pytest.raises(engine.Problem, match="different request"):
        engine.run_experiment("sim://thermal", "step", key="retry")
    with pytest.raises(engine.Problem):
        engine.apply_parameters("sim://thermal", {"kp":.02})
    engine.cancel_run(first["id"])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = engine.get_run(first["id"])
        if result["status"] == "cancelled":
            break
        time.sleep(.1)
    assert result["status"] == "cancelled"
    assert engine.review(first["id"])["samples"] == 0
    assert engine.apply_parameters("sim://thermal", {"kp":.02})["verified"]["kp"] == .02


def test_invalid_inputs_and_interrupted_acquisition():
    with pytest.raises(ValueError):
        engine.apply_parameters("sim://sensor", {"alpha":2})
    with pytest.raises(ValueError):
        engine.run_experiment("sim://sensor", "capture", goals={"delay_s":{"le":float("nan")}})
    result = engine.run_experiment("sim://sensor", "capture", fault="sample_gap")
    assert result["error"]["code"] == "sample_gap" and result["samples"] > 0
    assert "passed" not in result
    assert not engine.review(result["id"])["recomputed"]


def test_censored_time_fails_and_numeric_retry_is_idempotent():
    result = engine.run_experiment("sim://thermal", "step", conditions={"duration_s":10},
                                   goals={"rise_s":{"le":30}}, key="guard")
    assert result["metrics"]["reached"] == 0
    assert result["passed"] is False
    assert engine.review(result["id"])["passed"] is False
    same = engine.run_experiment("sim://thermal", "step", conditions={"duration_s":10.0},
                                 goals={"rise_s":{"le":30.0}}, key="guard")
    assert same["id"] == result["id"]


def test_mcp_bridge_accepts_sync_adapters_with_own_event_loop(monkeypatch):
    from looptrial import server
    def discover(uri):
        return asyncio.run(asyncio.sleep(0, result={"id":uri}))
    monkeypatch.setattr(engine, "describe", discover)
    assert asyncio.run(server.describe("serial://mock")) == {"id":"serial://mock"}


def test_plot_failure_keeps_raw_evidence(monkeypatch):
    def locked(*args):
        raise PermissionError("plot is locked")
    monkeypatch.setattr(engine.records, "plot", locked)
    run = engine.run_experiment("sim://sensor", "capture")
    assert run["status"] == "completed" and run["warnings"]
    assert engine.review(run["id"])["samples"] == 401


def test_interrupted_finalization_preserves_existing_csv():
    run = engine.run_experiment("sim://sensor", "capture")
    directory = engine.home() / "runs" / run["id"]
    (directory / "record.json").unlink()
    with engine.database() as db:
        db.execute("UPDATE jobs SET status='running',summary=NULL WHERE id=?", (run["id"],))
    recovered = engine.get_run(run["id"])
    assert recovered["error"]["code"] == "worker_lost" and recovered["samples"] == 401
    assert engine.review(run["id"])["samples"] == 401


def test_apply_mismatch_restoration_receipt(monkeypatch):
    from types import SimpleNamespace
    backend = SimpleNamespace(
        describe=lambda uri: {"id":"fixture","version":"1","parameters":{"gain":{"min":1,"max":3,"default":1}}},
        apply=lambda uri, params: params,
        read=lambda uri: {"gain":1})
    monkeypatch.setattr(engine, "backend", lambda uri: backend)
    with pytest.raises(engine.Problem) as raised:
        engine.apply_parameters("serial://fixture", {"gain":2})
    receipt = raised.value.details["receipt"]
    assert receipt["state"] == "restored" and receipt["last_readback"] == {"gain":1}
    assert engine.writes("serial://fixture")[0] == receipt
