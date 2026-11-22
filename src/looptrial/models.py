"""Deterministic virtual-clock instruments. Times in the trace are seconds."""

from __future__ import annotations

import math
import random
from collections import deque
from copy import deepcopy

from . import model_metrics


def _field(default, low, high, unit, description, *, integer=False):
    spec = dict(default=default, min=low, max=high, unit=unit, description=description)
    if integer:
        spec["type"] = "integer"
    return spec


def _signal(unit, description):
    return {"unit": unit, "description": description}


_TIME = _signal("s", "Elapsed virtual time at the recorded state.")
_SEED = _field(17, 0, 2**31 - 1, "1", "Repeat this seed for a paired input; change it for an independent noise draw.", integer=True)
_NOISE = _field(1, 0, 4, "kPa", "Standard deviation of independent Gaussian observation noise.")
_THERMAL = {
    "description": "Delayed first-order heater with a local PI controller. Each run starts at ambient with a cold, empty delay line.",
    "signals": {
        "t": _TIME,
        "temperature_c": _signal("degC", "Object temperature."),
        "target_c": _signal("degC", "Commanded working temperature."),
        "output": _signal("fraction", "Commanded heater duty, after clipping and before transport delay."),
    },
    "parameters": {
        "kp": _field(.012, .002, .16, "duty/degC", "Proportional heater gain."),
        "ki": _field(.0005, 0, .008, "duty/(degC*s)", "Integral gain with conditional anti-windup."),
    },
    "actions": {
        "step": {
            "description": "Apply a temperature reference step at t=0. Compare runs with the same reference, initial state and horizon.",
            "sample_period_s": .5,
            "conditions": {
                "target_c": _field(50, 26, 120, "degC", "Requested working temperature, above ambient."),
                "ambient_c": _field(20, 0, 35, "degC", "Ambient and initial object temperature."),
                "delay_s": _field(2, 0, 12, "s", "Heater-to-object dead time, in multiples of 0.5 s."),
                "heater_limit": _field(1, .05, 1, "fraction", "Maximum heater duty available."),
                "duration_s": _field(180, 10, 600, "s", "Observation window."),
            },
            "metrics": model_metrics.THERMAL,
        }
    },
}
_SENSOR = {
    "description": "Synthetic pressure reference and biased, noisy transducer with adjustable calibration and a single-pole filter. No actuator.",
    "signals": {
        "t": _TIME,
        "reference": _signal("kPa", "Known independently generated reference pressure."),
        "raw": _signal("kPa", "Nominal sensor reading before user calibration."),
        "calibrated": _signal("kPa", "scale * raw + offset."),
        "filtered": _signal("kPa", "Exponentially filtered calibrated pressure."),
    },
    "parameters": {
        "alpha": _field(1, .02, 1, "1", "Weight of the current sample. Lower values reduce noise and increase delay."),
        "scale": _field(1, .5, 1.5, "1", "Slope of the affine calibration."),
        "offset": _field(0, -10, 10, "kPa", "Additive calibration correction after scaling."),
    },
    "actions": {
        "capture": {
            "description": "Acquire a static 10 kPa reference followed by a step to 20 kPa at 3 s. The raw waveform is identical for a fixed noise condition and seed.",
            "sample_period_s": .02,
            "conditions": {
                "seed": _SEED, "noise_std": _NOISE,
                "duration_s": _field(8, 6, 30, "s", "Observation window, including both levels."),
            },
            "metrics": model_metrics.SENSOR,
        },
        "calibrate": {
            "description": "Acquire 50 readings at each reference. Fit raw-to-reference on the first two means, then evaluate bias on the held-out third point. No automatic writes.",
            "sample_period_s": .02,
            "conditions": {
                "seed": _SEED,
                "noise_std": _field(.2, 0, 4, "kPa", "Gaussian observation noise standard deviation."),
                "ref_low": _field(5, 0, 80, "kPa", "Lower fit standard."),
                "ref_high": _field(35, 0, 80, "kPa", "Upper fit standard."),
                "ref_check": _field(19, 0, 80, "kPa", "Independent held-out standard between the fit points."),
            },
            "metrics": model_metrics.CALIBRATION,
        },
    },
}
_MOTOR = {
    "description": "Forward-only wheel speed, a first-order motor under opposing constant load, with a local PI speed controller. Starts at rest.",
    "signals": {
        "t": _TIME,
        "speed_rpm": _signal("rpm", "Measured wheel speed."),
        "target_rpm": _signal("rpm", "Requested wheel speed."),
        "output": _signal("fraction", "Actual clipped drive command."),
    },
    "parameters": {
        "kp": _field(.003, .0005, .04, "duty/rpm", "Speed proportional gain."),
        "ki": _field(.004, 0, .09, "duty/(rpm*s)", "Speed integral gain with conditional anti-windup."),
    },
    "actions": {
        "step": {
            "description": "Step the reference at t=0. Observe a fixed initial zero speed, output ceiling, opposing load and final plateau.",
            "sample_period_s": .02,
            "conditions": {
                "target_rpm": _field(90, 5, 250, "rpm", "Commanded speed."),
                "load": _field(.08, 0, .8, "fraction", "Opposing load as equivalent full-drive fraction."),
                "drive_limit": _field(1, .05, 1, "fraction", "Maximum controller output."),
                "duration_s": _field(8, 2, 30, "s", "Observation window."),
            },
            "metrics": model_metrics.MOTOR,
        }
    },
}
_BALANCE = {
    "description": "Small-angle inverted pendulum above an accelerating wheel axle. A local full-state controller balances and recentres the axle.",
    "signals": {
        "t": _TIME,
        "angle_deg": _signal("deg", "Body tilt from upright, positive forward."),
        "position_m": _signal("m", "Horizontal axle displacement from the starting position."),
        "velocity_m_s": _signal("m/s", "Axle velocity."),
        "output": _signal("m/s^2", "Clipped axle acceleration command."),
    },
    "parameters": {
        "angle_gain": _field(19.5, 14, 28, "(m/s^2)/rad", "Body tilt feedback gain."),
        "rate_gain": _field(2.9, 1.8, 4.5, "(m/s^2)/(rad/s)", "Body angular rate feedback gain."),
    },
    "actions": {
        "disturb": {
            "description": "Hold upright at rest, impose a small angular displacement at 0.5 s, and observe recovery, axle excursion and commanded acceleration.",
            "sample_period_s": .01,
            "conditions": {
                "kick_deg": _field(3, .5, 7, "deg", "Repeatable positive displacement at 0.5 s."),
                "accel_limit": _field(4, .5, 6, "m/s^2", "Symmetric acceleration ceiling."),
                "duration_s": _field(6, 2, 10, "s", "Observation window."),
            },
            "metrics": model_metrics.BALANCE,
        }
    },
}

_DEVICES = {"sim://thermal": _THERMAL, "sim://sensor": _SENSOR, "sim://motor": _MOTOR, "sim://balance": _BALANCE}


def describe(uri):
    if uri not in _DEVICES:
        raise ValueError(f"unknown simulator {uri!r}; available: {', '.join(_DEVICES)}")
    return dict(id=uri, version="1.0", source="host-simulation", **deepcopy(_DEVICES[uri]))


def _values(spec, supplied):
    unknown = set(supplied) - set(spec)
    if unknown:
        raise ValueError("unknown field(s): " + ", ".join(sorted(unknown)))
    values = {}
    for name, field in spec.items():
        value = supplied.get(name, field["default"])
        if type(value) not in (int, float) or not field["min"] <= value <= field["max"]:
            raise ValueError(f"{name} must be a number in [{field['min']}, {field['max']}] {field['unit']}")
        if field.get("type") == "integer" and int(value) != value:
            raise ValueError(f"{name} must be an integer")
        values[name] = value
    return values


def _action(uri, action, conditions):
    device = describe(uri)
    if action not in device["actions"]:
        raise ValueError(f"unknown action {action!r} for {uri}")
    spec = device["actions"][action]
    c = _values(spec["conditions"], conditions)
    if uri == "sim://thermal":
        if c["target_c"] <= c["ambient_c"]:
            raise ValueError("target_c must be above ambient_c for a heating step")
        if not (c["delay_s"] / spec["sample_period_s"]).is_integer():
            raise ValueError("delay_s must be a multiple of the sample period")
    if action == "calibrate" and not c["ref_low"] < c["ref_check"] < c["ref_high"]:
        raise ValueError("ref_check must lie strictly between two distinct ordered fit standards")
    return device, spec, c


def _pi(error, integral, gain, rate, dt, ceiling):
    # Integrate while unsaturated, or when the error drives a saturated controller inward.
    raw = gain * error + integral
    if (raw < ceiling and error > 0) or (raw > 0 and error < 0):
        integral += rate * error * dt
    return min(ceiling, max(0., raw)), integral


def _thermal(c, p, dt, stamps):
    temp = c["ambient_c"]
    integral = 0.
    delay = deque([0.] * round(c["delay_s"] / dt))
    decay = math.exp(-dt / 35.)
    for t in stamps:
        duty, integral = _pi(c["target_c"] - temp, integral, p["kp"], p["ki"], dt, c["heater_limit"])
        yield dict(t=t, target_c=c["target_c"], temperature_c=temp, output=duty)
        delay.append(duty)
        equilibrium = c["ambient_c"] + 85. * delay.popleft()
        temp = equilibrium + (temp - equilibrium) * decay


def _motor(c, p, dt, stamps):
    speed = integral = 0.
    decay = math.exp(-dt / .42)
    for t in stamps:
        duty, integral = _pi(c["target_rpm"] - speed, integral, p["kp"], p["ki"], dt, c["drive_limit"])
        yield dict(t=t, target_rpm=c["target_rpm"], speed_rpm=speed, output=duty)
        equilibrium = 180. * max(0., duty - c["load"])
        speed = equilibrium + (speed - equilibrium) * decay


def _sensor(c, p, dt, stamps):
    rng = random.Random(c["seed"])
    filtered = None
    refs = [c["ref_low"], c["ref_high"], c["ref_check"]] if "ref_low" in c else None
    for i, t in enumerate(stamps):
        reference = refs[i // 50] if refs else (10. if t < 3 else 20.)
        raw = .8 + 1.08 * reference + rng.gauss(0, c["noise_std"])
        calibrated = p["scale"] * raw + p["offset"]
        if filtered is None:
            filtered = calibrated
        else:
            filtered += p["alpha"] * (calibrated - filtered)
        yield dict(t=t, reference=reference, raw=raw, calibrated=calibrated, filtered=filtered)


def _balance(c, p, dt, stamps):
    angle = rate = position = velocity = 0.
    for t in stamps:
        if t == .5:
            angle = math.radians(c["kick_deg"])
        # Positive forward tilt calls for forward wheel acceleration.
        command = p["angle_gain"] * angle + p["rate_gain"] * rate + .9 * position + 1.5 * velocity
        accel = max(-c["accel_limit"], min(c["accel_limit"], command))
        yield dict(t=t, angle_deg=math.degrees(angle), position_m=position, velocity_m_s=velocity, output=accel)
        angular_accel = (9.81 * angle - accel) / .25
        angle += dt * rate
        rate += dt * angular_accel
        position += dt * velocity
        velocity += dt * accel


_GENERATORS = {"sim://thermal": _thermal, "sim://sensor": _sensor, "sim://motor": _motor, "sim://balance": _balance}


def _count(action, conditions, period):
    if action == "calibrate":
        return 150
    return math.floor(conditions["duration_s"] / period + 1e-9) + 1


def acquire(uri, action, conditions, params, cancelled=lambda: False):
    device, spec, c = _action(uri, action, conditions)
    p = _values(device["parameters"], params)
    dt = spec["sample_period_s"]
    stamps = (round(i * dt, 9) for i in range(_count(action, c, dt)))
    rows = []
    for row in _GENERATORS[uri](c, p, dt, stamps):
        if cancelled():
            raise InterruptedError("simulation acquisition cancelled")
        rows.append(row)
    return rows


def metrics(uri, action, conditions, rows):
    device, spec, c = _action(uri, action, conditions)
    dt = spec["sample_period_s"]
    if len(rows) != _count(action, c, dt):
        raise ValueError(f"incomplete trace: expected {_count(action, c, dt)} samples, received {len(rows)}")
    for i, row in enumerate(rows):
        for key in device["signals"]:
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"invalid or missing {key} at sample {i}")
        if not math.isclose(row["t"], i * dt, rel_tol=0, abs_tol=1e-8):
            raise ValueError(f"sampling gap or incorrect timestamp at sample {i}")
    return model_metrics.evaluate(uri, action, c, rows)
