"""Route geometry and one camera-to-wheel end-to-end regression."""
import math
import shutil

import pytest

from looptrial import race


def defaults(course=1, **updates):
    specs = race.describe("race://yali")["actions"]["lap"]["conditions"]
    return {k: s["default"] for k, s in specs.items()} | {"course": course} | updates


def test_ordered_gates_finish_only_one_forward_lap():
    judge = race.Judge(defaults())
    length = 4 * judge.half + 2 * math.pi * judge.radius
    events = []
    for tick in range(1, 1002):
        x, z, _, _ = race._gate(tick * length / 1000, judge.radius, judge.half)
        proof = judge.observe({"x_m": x, "z_m": z, "t": tick/100})
        if proof["event"]:
            events.append(proof["event"])
        if proof["event"] == 2:
            break
    assert judge.count == 8
    assert events == [1]*7 + [2]


def test_skipped_gate_and_reversed_gate_are_terminal():
    for gate_index, direction, expected in [(2, 1, 4), (0, -1, 6)]:
        judge = race.Judge(defaults())
        x, z, tx, tz = judge.gates[gate_index]
        judge.previous = (x-direction*0.01*tx, z-direction*0.01*tz)
        observed = judge.observe({"x_m":x+direction*0.01*tx, "z_m":z+direction*0.01*tz, "t":0.1})
        assert observed["event"] == expected
        assert judge.count == 0


def test_corner_cut_and_timeout_are_terminal():
    judge = race.Judge(defaults())
    assert judge.observe({"x_m":0,"z_m":0,"t":0.1})["event"] == 3
    judge = race.Judge(defaults(timeout_s=1))
    assert judge.observe({"x_m":-judge.radius,"z_m":0,"t":1})["event"] == 5


def test_installed_webgl_camera_causally_drives_vehicle(monkeypatch, tmp_path):
    try:
        race._browser()
    except ValueError:
        pytest.skip("a Chromium-based browser is required for the optical loop")
    conditions = defaults()
    settings = {"drive_speed":250, "steer_gain":10.85}

    def run(c, settings):
        rows = race.acquire("race://yali", "lap", c, settings, lambda: False)
        return rows, race.metrics("race://yali", "lap", c, rows)

    rows, baseline = run(conditions, settings)
    assert baseline["valid_lap"] and baseline["gates_passed"] == 8
    rows[2]["x_m"] += 0.02
    with pytest.raises(ValueError, match="wheel-driven motion"):
        race.metrics("race://yali", "lap", conditions, rows)
    faster = {**settings, "drive_speed":320}
    _, candidate = run(conditions, faster)
    _, confirm = run(defaults(seed=41), faster)
    assert candidate["valid_lap"] and confirm["valid_lap"]
    assert max(candidate["lap_time_s"], confirm["lap_time_s"]) < baseline["lap_time_s"]

    # Work on a private copy. Remove only the painted stripe, keeping the
    # course identically shaped for the independent ground-truth judge.
    assets = tmp_path / "blinded"
    shutil.copytree(race.ASSETS, assets)
    scene = assets / "lap.js"
    text = scene.read_text(encoding="utf-8")
    assert 'pen.strokeStyle = "#ffffff"' in text
    scene.write_text(text.replace('pen.strokeStyle = "#ffffff"', 'pen.strokeStyle = "#061a3a"'), encoding="utf-8")
    monkeypatch.setattr(race, "ASSETS", assets)
    blind_rows, blind = run(conditions, settings)
    assert blind["valid_lap"] == 0 and blind["stop_event"] == 3
    assert max(r["visible_rows"] for r in blind_rows) == 0
