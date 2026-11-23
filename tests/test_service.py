import asyncio
import json
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


def test_offline_review_rejects_unknown_rule_operator():
    run = engine.run_experiment("sim://sensor", "capture", goals={"noise_std":{"ge":0}})
    path = engine.home() / run["record"]
    record = json.loads(path.read_text(encoding="utf-8"))
    record["goals"]["noise_std"] = {"gt": 0}
    record["checks"]["goals"][0]["op"] = "gt"
    engine.records.write_json(path, record)
    with pytest.raises(ValueError, match="rules use"):
        engine.review(str(path))


def test_changed_final_readback_retains_samples_without_publishing_a_verdict(monkeypatch):
    initial_read = engine._read
    readings = 0
    def changed_read(adapter, uri, info):
        nonlocal readings
        readings += 1
        values = initial_read(adapter, uri, info)
        return values if readings == 1 else values | {"alpha":0.2}
    monkeypatch.setattr(engine, "_read", changed_read)
    result = engine.run_experiment("sim://sensor", "capture", goals={"noise_std":{"ge":0}})
    assert result["status"] == "failed" and result["error"]["code"] == "readback_mismatch"
    assert result["samples"] == 401 and result["device_state"]["values"]["alpha"] == .2
    assert not result["checks"] and not result["metrics"] and "passed" not in result


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


def _export_with_edits(tmp_path, name, run_id, **updates):
    target = tmp_path / name
    shutil.copytree(engine.home() / "runs" / run_id, target)
    path = target / "record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    engine.records.write_json(path, record)
    return target


def _write_portable_record(directory, record, rows):
    directory.mkdir(parents=True, exist_ok=True)
    record = dict(record, samples=len(rows), samples_sha256=engine.records.write_samples(directory, rows))
    engine.records.write_json(directory / "record.json", record)
    return directory


def test_compare_requires_matching_parameter_names_and_metric_units(tmp_path):
    baseline = engine.run_experiment("sim://thermal", "step")
    changed_params = _export_with_edits(tmp_path, "new-field", baseline["id"],
                                        parameters=baseline["parameters"] | {"extra": 1})
    changed_units = _export_with_edits(tmp_path, "other-units", baseline["id"],
                                       metric_units=baseline["metric_units"] | {"rise_s": "ms"})
    for candidate in (changed_params, changed_units):
        for first, second in ((baseline["id"], str(candidate)), (str(candidate), baseline["id"])):
            with pytest.raises(engine.Problem) as exc:
                engine.compare(first, second)
            assert exc.value.code == "incomparable"


def test_compare_censored_event_times_across_all_sides():
    conditions = {"duration_s": 60}
    engine.apply_parameters("sim://thermal", {"kp": .002, "ki": 0})
    censored_a = engine.run_experiment("sim://thermal", "step", conditions=conditions)
    engine.apply_parameters("sim://thermal", {"kp": .004, "ki": 0})
    censored_b = engine.run_experiment("sim://thermal", "step", conditions=conditions)
    engine.apply_parameters("sim://thermal", {"kp": .05, "ki": .002})
    observed_a = engine.run_experiment("sim://thermal", "step", conditions=conditions)
    engine.apply_parameters("sim://thermal", {"kp": .16, "ki": .002})
    observed_b = engine.run_experiment("sim://thermal", "step", conditions=conditions)

    assert censored_a["metrics"]["reached"] == 0 and censored_b["metrics"]["reached"] == 0
    assert observed_a["metrics"]["reached"] == 1 and observed_b["metrics"]["reached"] == 1

    first_censored = engine.compare(censored_a["id"], observed_a["id"])
    assert "rise_s" not in first_censored["delta"]
    assert first_censored["unavailable_delta"] == {
        "rise_s": {"event": "reached", "first_observed": False, "second_observed": True},
    }
    assert first_censored["unavailable_delta"]["rise_s"]["first_observed"] is False
    assert first_censored["unavailable_delta"]["rise_s"]["second_observed"] is True
    assert first_censored["delta"]["reached"] == 1
    assert first_censored["delta"]["steady_error_c"] == (
        observed_a["metrics"]["steady_error_c"] - censored_a["metrics"]["steady_error_c"]
    )
    json.dumps(first_censored, allow_nan=False)

    second_censored = engine.compare(observed_a["id"], censored_a["id"])
    assert "rise_s" not in second_censored["delta"]
    assert second_censored["unavailable_delta"] == {
        "rise_s": {"event": "reached", "first_observed": True, "second_observed": False},
    }
    assert second_censored["delta"]["reached"] == -1
    assert second_censored["delta"]["tail_temperature_c"] == (
        censored_a["metrics"]["tail_temperature_c"] - observed_a["metrics"]["tail_temperature_c"]
    )

    both_censored = engine.compare(censored_a["id"], censored_b["id"])
    assert "rise_s" not in both_censored["delta"]
    assert both_censored["unavailable_delta"] == {
        "rise_s": {"event": "reached", "first_observed": False, "second_observed": False},
    }
    assert both_censored["delta"]["reached"] == 0
    assert both_censored["delta"]["tail_temperature_c"] == (
        censored_b["metrics"]["tail_temperature_c"] - censored_a["metrics"]["tail_temperature_c"]
    )

    neither_censored = engine.compare(observed_a["id"], observed_b["id"])
    assert neither_censored["unavailable_delta"] == {}
    assert neither_censored["delta"]["rise_s"] == (
        observed_b["metrics"]["rise_s"] - observed_a["metrics"]["rise_s"]
    )
    assert neither_censored["delta"]["reached"] == 0


def test_compare_legacy_builtin_records_and_version_compatibility(tmp_path):
    from looptrial import models

    conditions = {"duration_s": 40}
    engine.apply_parameters("sim://thermal", {"kp": .002, "ki": 0})
    censored = engine.run_experiment("sim://thermal", "step", conditions=conditions)
    engine.apply_parameters("sim://thermal", {"kp": .16, "ki": .002})
    observed = engine.run_experiment("sim://thermal", "step", conditions=conditions)

    old_a = _export_with_edits(tmp_path, "thermal_old_a", censored["id"], requires_event=None)
    old_b = _export_with_edits(tmp_path, "thermal_old_b", observed["id"], requires_event=None)
    legacy_thermal = engine.compare(str(old_a), str(old_b))
    assert "rise_s" not in legacy_thermal["delta"]
    assert legacy_thermal["unavailable_delta"] == {
        "rise_s": {"event": "reached", "first_observed": False, "second_observed": True},
    }
    assert legacy_thermal["delta"]["reached"] == 1

    future_a = _export_with_edits(tmp_path, "thermal_v2_a", censored["id"], requires_event=None, version="2.0")
    future_b = _export_with_edits(tmp_path, "thermal_v2_b", observed["id"], requires_event=None, version="2.0")
    with pytest.raises(ValueError, match="unsupported evaluator version"):
        engine.compare(str(future_a), str(future_b))

    # Practical version compatibility: sim://sensor 1.0 records lack requires_event
    # while the current sim://sensor contract is 1.1.
    sensor_conditions = {"seed": 17, "noise_std": 0, "duration_s": 6}
    rows_obs = models.acquire("sim://sensor", "capture", sensor_conditions, {"alpha": .25})
    rows_cen = [dict(r, filtered=10.0) for r in rows_obs]
    rows_cen[-2]["filtered"] = 20.0
    rows_cen[-1]["filtered"] = 20.0
    metrics_cen = models.metrics("sim://sensor", "capture", sensor_conditions, rows_cen, version="1.0")
    metrics_obs = models.metrics("sim://sensor", "capture", sensor_conditions, rows_obs, version="1.0")
    assert metrics_cen["reached"] == 0 and metrics_obs["reached"] == 1
    base_sensor = dict(
        format=1, looptrial="0.1.0", status="completed", source="sim://sensor",
        device="sim://sensor", version="1.0", action="capture", conditions=sensor_conditions,
        goals={}, constraints={}, checks={"goals": [], "constraints": []}, passed=None,
        device_state={"state": "verified"},
    )
    v10_cen = _write_portable_record(
        tmp_path / "sensor_v10_cen",
        dict(base_sensor, id="a" * 32, parameters={"alpha": .02, "scale": 1, "offset": 0}, metrics=metrics_cen),
        rows_cen,
    )
    v10_obs = _write_portable_record(
        tmp_path / "sensor_v10_obs",
        dict(base_sensor, id="b" * 32, parameters={"alpha": .25, "scale": 1, "offset": 0}, metrics=metrics_obs),
        rows_obs,
    )
    legacy_sensor = engine.compare(str(v10_cen), str(v10_obs))
    assert "delay_s" not in legacy_sensor["delta"]
    assert legacy_sensor["unavailable_delta"] == {
        "delay_s": {"event": "reached", "first_observed": False, "second_observed": True},
    }
    assert legacy_sensor["delta"]["reached"] == 1


def test_compare_keeps_invalid_lap_rejection(tmp_path):
    import math
    from looptrial import race

    info = race.describe("race://yali")
    conditions = {k: s["default"] for k, s in info["actions"]["lap"]["conditions"].items()}
    judge = race.Judge(conditions)
    rows = []
    # Two physically consistent 10 ms steps: first stays on line, second exits lane width.
    for index, (speed, yaw) in enumerate([(1.0, 0.0), (10.0, math.pi / 2)], 1):
        px, pz = judge.previous
        step = speed / 100
        row = {
            "t": index / 100,
            "x_m": px - math.sin(yaw) * step,
            "z_m": pz - math.cos(yaw) * step,
            "yaw_rad": yaw,
            "speed_m_s": speed,
            "visual_error_px": 0.0,
            "visible_rows": 10,
            "pwm_l": 100.0,
            "pwm_r": 100.0,
        }
        row.update(judge.observe(row))
        rows.append(row)
    metrics = race.metrics("race://yali", "lap", conditions, rows)
    assert metrics["valid_lap"] == 0 and metrics["stop_event"] == 3
    base = dict(
        format=1, looptrial="0.2.2", status="completed", source="race://yali",
        device=info["id"], version=info["version"], action="lap", conditions=conditions,
        goals={}, constraints={}, checks={"goals": [], "constraints": []}, passed=None,
        device_state={"state": "verified"}, metrics=metrics,
    )
    lap_a = _write_portable_record(
        tmp_path / "lap_a", dict(base, id="1" * 32, parameters={"drive_speed": 250, "steer_gain": 10.85}), rows,
    )
    lap_b = _write_portable_record(
        tmp_path / "lap_b", dict(base, id="2" * 32, parameters={"drive_speed": 300, "steer_gain": 10.85}), rows,
    )
    with pytest.raises(engine.Problem, match="invalid lap") as raised:
        engine.compare(str(lap_a), str(lap_b))
    assert raised.value.code == "incomparable"


def test_compare_does_not_guess_unknown_adapter_semantics(monkeypatch):
    from types import SimpleNamespace

    describe_calls = 0

    def make_adapter(declare_event):
        metric_spec = {
            "reached": {"unit": "0/1"},
            "rise_s": {"unit": "s", **({"requires_event": "reached"} if declare_event else {})},
            "level": {"unit": "u"},
        }

        def describe(uri):
            nonlocal describe_calls
            describe_calls += 1
            return {
                "id": "custom-bench", "version": "1.0",
                "signals": {"t": {"unit": "s"}, "y": {"unit": "u"}},
                "parameters": {"mode": {"min": 0, "max": 1, "default": 0, "type": "integer"}},
                "actions": {"probe": {"conditions": {}, "metrics": metric_spec}},
            }

        def acquire(uri, action, conditions, params, cancelled):
            return [{"t": 0.0, "y": float(params["mode"])}, {"t": 1.0, "y": float(params["mode"])}]

        def metrics(uri, action, conditions, rows):
            mode = int(rows[-1]["y"])
            return {"reached": mode, "rise_s": 4.0 if mode else 10.0, "level": 2.0 + mode}

        return SimpleNamespace(describe=describe, acquire=acquire, metrics=metrics)

    unknown = make_adapter(declare_event=False)
    monkeypatch.setattr(engine, "backend", lambda uri: unknown)
    first = engine.run_experiment("custom://bench", "probe")
    engine.apply_parameters("custom://bench", {"mode": 1})
    second = engine.run_experiment("custom://bench", "probe")
    calls_before_compare = describe_calls
    compared_unknown = engine.compare(first["id"], second["id"])
    assert describe_calls == calls_before_compare
    assert compared_unknown["unavailable_delta"] == {}
    assert compared_unknown["delta"] == {"reached": 1, "rise_s": -6.0, "level": 1.0}

    declared = make_adapter(declare_event=True)
    monkeypatch.setattr(engine, "backend", lambda uri: declared)
    engine.apply_parameters("custom://bench2", {"mode": 0})
    third = engine.run_experiment("custom://bench2", "probe")
    engine.apply_parameters("custom://bench2", {"mode": 1})
    fourth = engine.run_experiment("custom://bench2", "probe")
    calls_before_compare = describe_calls
    compared_declared = engine.compare(third["id"], fourth["id"])
    assert describe_calls == calls_before_compare
    assert "rise_s" not in compared_declared["delta"]
    assert compared_declared["unavailable_delta"] == {
        "rise_s": {"event": "reached", "first_observed": False, "second_observed": True},
    }
    assert compared_declared["delta"] == {"reached": 1, "level": 1.0}
