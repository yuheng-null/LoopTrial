import math
from statistics import fmean

import pytest

from looptrial import models


def trial(uri, action, conditions=None, params=None):
    uri = "sim://" + uri
    conditions = conditions or {}
    rows = models.acquire(uri, action, conditions, params or {})
    result = models.metrics(uri, action, conditions, rows)
    assert set(result) == set(models.describe(uri)["actions"][action]["metrics"])
    return rows, result


def test_heater_at_constant_limit_matches_delayed_closed_form():
    conditions = dict(ambient_c=18, target_c=100, delay_s=3, heater_limit=.25, duration_s=100)
    rows, result = trial("thermal", "step", conditions, {"kp": .16})
    for row in rows:
        elapsed = max(0, row["t"] - 3)
        expected = 18 + .25 * 85 * (1 - math.exp(-elapsed / 35))
        assert row["temperature_c"] == pytest.approx(expected)
    assert result["saturation_fraction"] == 1
    assert result["reached"] == 0
    assert result["rise_s"] == result["sat_longest_end_s"] == 100
    assert result["sat_longest_start_s"] == 0


def test_thermal_conditions_and_gains_change_response():
    baseline, slow = trial("thermal", "step")
    faster, fast = trial("thermal", "step", params={"kp": .05, "ki": .0016})
    assert slow["rise_s"] > fast["rise_s"]
    assert fast["overshoot_c"] < 1
    assert all(r["target_c"] == 50 for r in baseline + faster)
    other, _ = trial("thermal", "step", {"target_c": 60})
    assert all(r["target_c"] == 60 for r in other)
    assert other[25]["temperature_c"] != baseline[25]["temperature_c"]


def test_measured_step_metrics_on_hand_constructed_trace():
    # Last 3 of 21 samples sit at 49, 50 and 53 C, for an absolute mean error of 4/3.
    temps = [20.] * 12 + [48.6] * 6 + [49., 50., 53.]
    drives = [.9] * 21
    drives[1:4] = [1.] * 3
    drives[10:15] = [1.] * 5
    rows = [dict(t=i/2, temperature_c=temp, target_c=50., output=drives[i]) for i, temp in enumerate(temps)]
    m = models.metrics("sim://thermal", "step", {"duration_s": 10}, rows)
    assert m["rise_s"] == 6
    assert m["overshoot_c"] == 3
    assert m["steady_error_c"] == pytest.approx(4 / 3)
    assert m["saturation_fraction"] == pytest.approx(8 / 21)
    assert (m["sat_longest_start_s"], m["sat_longest_end_s"]) == (5, 7)


def test_filter_same_input_exact_noiseless_step_delay():
    # y[n] = target - amplitude*(1-alpha)**(n+1), including n=0 at the step.
    params = {"alpha": .25}
    base, _ = trial("sensor", "capture", {"noise_std": 0})
    rows, metrics = trial("sensor", "capture", {"noise_std": 0}, params)
    assert [r["raw"] for r in base] == [r["raw"] for r in rows]
    n90 = math.ceil(math.log(.1) / math.log(.75)) - 1
    assert metrics["delay_s"] == pytest.approx(n90 * .02)
    assert metrics["noise_std"] == pytest.approx(0)
    assert metrics["reached"] == 1


def test_filter_noise_is_measured_over_static_window_and_pairs_input():
    raw, direct = trial("sensor", "capture")
    smooth, filtered = trial("sensor", "capture", params={"alpha": .12})
    assert all(a["raw"] == b["raw"] for a, b in zip(raw, smooth))
    x = [r["raw"] for r in raw if 1 <= r["t"] < 3]
    expected = math.sqrt(sum((v - fmean(x))**2 for v in x) / len(x))
    assert direct["noise_std"] == pytest.approx(expected)
    assert filtered["noise_std"] < direct["noise_std"]
    assert filtered["delay_s"] > direct["delay_s"]
    fresh, _ = trial("sensor", "capture", {"seed": 18})
    assert fresh[0]["raw"] != raw[0]["raw"]


def test_two_point_calibration_predicts_unseen_point_and_readback():
    conditions = {"ref_low": 5, "ref_high": 35, "ref_check": 26, "noise_std": 0}
    rows, m = trial("sensor", "calibrate", conditions)
    assert m["fit_scale"] == pytest.approx(1 / 1.08)
    assert m["fit_offset"] == pytest.approx(-.8 / 1.08)
    assert m["raw_residual"] == pytest.approx(.8 + .08 * 26)
    assert m["fitted_residual"] == pytest.approx(0, abs=1e-12)
    _, checked = trial("sensor", "calibrate", conditions, {"scale": m["fit_scale"], "offset": m["fit_offset"]})
    assert checked["applied_residual"] == pytest.approx(0, abs=1e-12)
    for r in rows[100:]:
        r["raw"] += 2
    perturbed = models.metrics("sim://sensor", "calibrate", conditions, rows)
    assert perturbed["fit_scale"] == m["fit_scale"]
    assert perturbed["fitted_residual"] == pytest.approx(2 / 1.08)


def test_motor_limited_speed_plateau_and_tuning():
    _, stopped = trial("motor", "step", {"target_rpm": 180, "drive_limit": .6})
    assert stopped["reached"] == 0
    assert stopped["tail_speed_rpm"] == pytest.approx(180 * (.6 - .08), abs=.001)
    assert stopped["tail_slope_rpm_s"] < .001
    assert stopped["tail_output_mean"] == pytest.approx(.6)
    _, base = trial("motor", "step")
    _, tuned = trial("motor", "step", params={"kp": .012, "ki": .022})
    assert tuned["reached"] == 1
    assert tuned["rise_s"] < base["rise_s"] / 2


def test_balance_joint_metrics_and_disturbance():
    rows, m = trial("balance", "disturb")
    assert all(r["angle_deg"] == r["position_m"] == r["output"] == 0 for r in rows[:50])
    assert rows[50]["angle_deg"] == pytest.approx(3)
    assert m["small_angle_valid"] == m["recovered"] == 1
    assert m["peak_output"] == pytest.approx(math.radians(3) * 19.5)
    assert 0 < m["max_drift_m"] < .15
    assert m["final_drift_m"] < .001
    crossing = max(r["t"] for r in rows if abs(r["angle_deg"]) > .2) + .01
    assert m["recovery_s"] == pytest.approx(crossing - .5)
    _, clipped = trial("balance", "disturb", {"kick_deg": 7, "accel_limit": .5, "duration_s": 2})
    assert clipped["saturation_fraction"] > 0
    assert clipped["small_angle_valid"] == clipped["recovered"] == 0


@pytest.mark.parametrize("conditions", [
    {"target_c": False}, {"noise_std": 1}, {"delay_s": .75}, {"target_c": float("nan")},
    {"target_c": 27, "ambient_c": 30}, {"duration_s": 600.1},
])
def test_invalid_conditions(conditions):
    with pytest.raises(ValueError):
        models.acquire("sim://thermal", "step", conditions, {})


def test_incomplete_or_incomparable_trials_do_not_score():
    rows, _ = trial("thermal", "step")
    with pytest.raises(ValueError, match="incomplete"):
        models.metrics("sim://thermal", "step", {}, rows[:-1])
    with pytest.raises(ValueError, match="initial state"):
        models.metrics("sim://thermal", "step", {"ambient_c": 22}, rows)
    with pytest.raises(ValueError, match="step target"):
        models.metrics("sim://thermal", "step", {"target_c": 60}, rows)
    rows[20]["t"] += .1
    with pytest.raises(ValueError, match="sampling gap"):
        models.metrics("sim://thermal", "step", {}, rows)


def test_sensor_needs_independent_standards_and_valid_seed():
    with pytest.raises(ValueError, match="distinct"):
        models.acquire("sim://sensor", "calibrate", {"ref_check": 35}, {})
    with pytest.raises(ValueError, match="integer"):
        models.acquire("sim://sensor", "capture", {"seed": .5}, {})


def test_local_cancellation_stops_generator():
    with pytest.raises(InterruptedError):
        models.acquire("sim://balance", "disturb", {}, {}, cancelled=lambda: True)
