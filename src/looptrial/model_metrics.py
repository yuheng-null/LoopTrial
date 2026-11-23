"""Offline estimators for the supplied simulated instruments, based on recorded signals."""

import math
from statistics import fmean, pstdev


def _m(unit, description, requires_event=None):
    metric = {"unit": unit, "description": description}
    if requires_event:
        metric["requires_event"] = requires_event
    return metric


_RISE = {
    "reached": _m("0/1", "Reached 95% of the requested step at least once."),
    "rise_s": _m("s", "First measured time at or above 95% of the step from its initial value. If reached=0, the observation ends here and the time is censored.", "reached"),
    "saturation_fraction": _m("fraction", "Fraction of samples at the configured positive output ceiling."),
    "sat_longest_start_s": _m("s", "Start time of longest contiguous interval at the ceiling, or 0 if none."),
    "sat_longest_end_s": _m("s", "Time of last sample in that interval, or 0 if none."),
    "tail_output_mean": _m("fraction", "Mean applied command over the final 10% of the samples."),
}
THERMAL = {
    **_RISE,
    "overshoot_c": _m("degC", "Peak excursion above the working temperature; zero if no overshoot."),
    "steady_error_c": _m("degC", "Mean absolute tracking error over the final 10% of samples."),
    "tail_temperature_c": _m("degC", "Final 10% mean temperature."),
    "tail_slope_c_s": _m("degC/s", "Endpoint slope over the final 10% of the samples."),
}
MOTOR = {
    **_RISE,
    "overshoot_rpm": _m("rpm", "Peak speed above the target."),
    "steady_error_rpm": _m("rpm", "Mean absolute tracking error over the final 10% of samples."),
    "tail_speed_rpm": _m("rpm", "Final 10% mean speed."),
    "tail_slope_rpm_s": _m("rpm/s", "Endpoint slope over the final 10% of the samples, useful for judging a speed plateau."),
}
SENSOR = {
    "noise_std": _m("kPa", "Population standard deviation of filtered readings over the static window 1 <= t < 3 s."),
    "raw_noise_std": _m("kPa", "Population standard deviation of uncorrected readings over that same static window."),
    "delay_s": _m("s", "Time from reference step to the first of three consecutive filtered samples at or above 90% of the measured calibrated input step. If reached=0, time is censored at the last sample.", "reached"),
    "reached": _m("0/1", "Observed the sustained 90% crossing."),
}
CALIBRATION = {
    "fit_scale": _m("1", "Slope from the mean raw readings of the two fit standards."),
    "fit_offset": _m("kPa", "Intercept from the same two standards. Correction = fit_scale * raw + fit_offset."),
    "raw_low": _m("kPa", "Mean raw reading at the lower fit standard."),
    "raw_high": _m("kPa", "Mean raw reading at the upper fit standard."),
    "raw_check": _m("kPa", "Mean raw reading at the held-out standard."),
    "raw_residual": _m("kPa", "Held-out raw mean minus independent reference."),
    "fitted_residual": _m("kPa", "Held-out mean corrected with fitted coefficients minus reference."),
    "applied_residual": _m("kPa", "Held-out mean corrected with the device's actual coefficients minus reference."),
}
BALANCE = {
    "recovered": _m("0/1", "Tilt returned to ±0.2 deg through the end, for at least 0.25 s."),
    "recovery_s": _m("s", "Time from disturbance until tilt stays in that band. Censored at the end when recovered=0.", "recovered"),
    "peak_angle_deg": _m("deg", "Peak absolute tilt."),
    "small_angle_valid": _m("0/1", "All measured tilts remain within the declared ±12 deg linear-model validity band."),
    "max_drift_m": _m("m", "Peak absolute axle displacement from its starting point."),
    "final_drift_m": _m("m", "Absolute axle displacement at the end."),
    "peak_output": _m("m/s^2", "Peak absolute commanded axle acceleration."),
    "saturation_fraction": _m("fraction", "Fraction of samples at either acceleration limit."),
}


def _matching(values, expected, name):
    if any(not math.isclose(actual, expected, rel_tol=0., abs_tol=1e-8) for actual in values):
        raise ValueError(f"recorded {name} differs from the declared trial conditions")


def _saturation(rows, ceiling):
    start = None
    best_length = count = 0
    best_a = best_b = 0.
    for i, row in enumerate(rows):
        if math.isclose(row["output"], ceiling, abs_tol=1e-9, rel_tol=0):
            count += 1
            if start is None:
                start = i
            length = i - start + 1
            if length > best_length:
                best_length = length
                best_a, best_b = rows[start]["t"], row["t"]
        else:
            start = None
    return {"saturation_fraction": count / len(rows), "sat_longest_start_s": best_a, "sat_longest_end_s": best_b}


def _step(rows, signal, target_signal, initial, target, ceiling):
    _matching([rows[0][signal]], initial, "initial state")
    _matching((r[target_signal] for r in rows), target, "step target")
    threshold = initial + .95 * (target - initial)
    crossing = next((r["t"] for r in rows if r[signal] >= threshold), None)
    tail = rows[-max(2, math.ceil(len(rows) / 10)):]
    common = _saturation(rows, ceiling)
    common.update(
        reached=int(crossing is not None),
        rise_s=rows[-1]["t"] if crossing is None else crossing,
        tail_output_mean=fmean(r["output"] for r in tail),
    )
    overshoot = max(0., max(r[signal] for r in rows) - target)
    error = fmean(abs(r[signal] - target) for r in tail)
    mean = fmean(r[signal] for r in tail)
    slope = (tail[-1][signal] - tail[0][signal]) / (tail[-1]["t"] - tail[0]["t"])
    return common, overshoot, error, mean, slope


def _sensor(rows, level_signal):
    for row in rows:
        _matching([row["reference"]], 10. if row["t"] < 3 else 20., "reference waveform")
    static = [r for r in rows if 1 <= r["t"] < 3]
    low = fmean(r[level_signal] for r in static)
    high = fmean(r[level_signal] for r in rows if r["t"] >= rows[-1]["t"] - 1)
    if high <= low:
        raise ValueError("measured levels do not resolve the positive reference step")
    threshold = low + .9 * (high - low)
    count = 0
    crossing = None
    for i, r in enumerate(rows):
        if r["t"] >= 3 and r["filtered"] >= threshold:
            count += 1
            if count == 3:
                crossing = rows[i - 2]["t"]
                break
        else:
            count = 0
    return {
        "noise_std": pstdev(r["filtered"] for r in static),
        "raw_noise_std": pstdev(r["raw"] for r in static),
        "reached": int(crossing is not None),
        "delay_s": round((rows[-1]["t"] if crossing is None else crossing) - 3., 9),
    }


def _calibration(c, rows):
    means = []
    for i, name in enumerate(("ref_low", "ref_high", "ref_check")):
        segment = rows[i * 50:(i + 1) * 50]
        _matching((r["reference"] for r in segment), c[name], "calibration reference")
        means.append(fmean(r["raw"] for r in segment))
    low, high, check = means
    if high <= low:
        raise ValueError("measured fit standards do not resolve a positive calibration slope")
    scale = (c["ref_high"] - c["ref_low"]) / (high - low)
    offset = c["ref_low"] - scale * low
    return {
        "fit_scale": scale, "fit_offset": offset, "raw_low": low, "raw_high": high, "raw_check": check,
        "raw_residual": check - c["ref_check"],
        "fitted_residual": scale * check + offset - c["ref_check"],
        "applied_residual": fmean(r["calibrated"] for r in rows[100:]) - c["ref_check"],
    }


def _balance(c, rows):
    kick_time = .5
    kick_index = round(kick_time / (rows[1]["t"] - rows[0]["t"]))
    _matching((r["angle_deg"] for r in rows[:kick_index]), 0., "initial tilt")
    _matching([rows[kick_index]["angle_deg"]], c["kick_deg"], "angular disturbance")
    outside = [i for i, r in enumerate(rows) if i >= kick_index and abs(r["angle_deg"]) > .2]
    settled = outside[-1] + 1
    recovered = settled < len(rows) and rows[-1]["t"] - rows[settled]["t"] >= .25
    peak = max(abs(r["angle_deg"]) for r in rows)
    saturated = sum(math.isclose(abs(r["output"]), c["accel_limit"], abs_tol=1e-9, rel_tol=0) for r in rows)
    return {
        "recovered": int(recovered), "recovery_s": (rows[settled]["t"] if recovered else rows[-1]["t"]) - kick_time,
        "peak_angle_deg": peak, "small_angle_valid": int(peak <= 12),
        "max_drift_m": max(abs(r["position_m"]) for r in rows), "final_drift_m": abs(rows[-1]["position_m"]),
        "peak_output": max(abs(r["output"]) for r in rows), "saturation_fraction": saturated / len(rows),
    }


def evaluate(uri, action, c, rows, *, version=None):
    if uri == "sim://thermal":
        common, peak, error, mean, slope = _step(
            rows, "temperature_c", "target_c", c["ambient_c"], c["target_c"], c["heater_limit"]
        )
        return dict(common, overshoot_c=peak, steady_error_c=error, tail_temperature_c=mean, tail_slope_c_s=slope)
    if uri == "sim://motor":
        common, peak, error, mean, slope = _step(rows, "speed_rpm", "target_rpm", 0, c["target_rpm"], c["drive_limit"])
        return dict(common, overshoot_rpm=peak, steady_error_rpm=error, tail_speed_rpm=mean, tail_slope_rpm_s=slope)
    if uri == "sim://sensor":
        return _calibration(c, rows) if action == "calibrate" else _sensor(rows, "filtered" if version == "1.0" else "calibrated")
    if uri == "sim://balance":
        return _balance(c, rows)
    raise ValueError(f"unknown metric family for {uri}")
