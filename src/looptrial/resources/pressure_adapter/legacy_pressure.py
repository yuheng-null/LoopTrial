"""SPDX-License-Identifier: GPL-3.0-or-later. Example read-only logger adapter."""

import csv
import hashlib
import io
import os
from pathlib import Path
from statistics import fmean


# Synthetic exported readings in an older logger's native file format.
FIXTURE = b"""timestamp_ms,adc_count
640,500
660,501
680,503
700,500
720,499
740,507
760,502
780,500
"""


def _input(uri):
    if uri == "pressure://fixture":
        return FIXTURE
    path = os.environ.get("LOOPTRIAL_PRESSURE_LOG")
    if not path:
        raise ValueError("Set LOOPTRIAL_PRESSURE_LOG to an exported CSV and use pressure://<its SHA-256>.")
    with Path(path).open("rb") as stream:
        data = stream.read(65_537)
    if len(data) > 65_536:
        raise ValueError("example adapter accepts up to 64 KiB per export")
    if uri != "pressure://" + hashlib.sha256(data).hexdigest():
        raise ValueError("CSV differs from the requested logger export")
    return data


def describe(uri):
    log_id = hashlib.sha256(_input(uri)).hexdigest()
    return {
        "id": "pressure-log-" + log_id, "version": "csv-v1", "source": "log-replay",
        "signals": {
            "t": {"unit": "s", "description": "Seconds from first frame"},
            "adc_count": {"unit": "count", "description": "12-bit nominal pressure sensor reading"},
            "pressure": {"unit": "kPa", "description": "(adc_count - 50) * 0.05, logger's nominal mapping"},
        },
        "parameters": {},
        "actions": {"ripple": {
            "description": "Measure pressure variation across a contiguous 50 Hz window of archived frames.",
            "sample_period_s": .02,
            "conditions": {"samples": {"type": "integer", "unit": "samples", "default": 8, "min": 2, "max": 2000}},
            "metrics": {
                "peak_to_peak_kpa": {"unit": "kPa", "description": "Maximum pressure minus minimum"},
                "mean_kpa": {"unit": "kPa", "description": "Arithmetic mean pressure in the captured window"},
            },
        }},
    }


def acquire(uri, action, conditions, params, cancelled):
    reader = csv.DictReader(io.StringIO(_input(uri).decode("utf-8-sig")))
    if reader.fieldnames != ["timestamp_ms", "adc_count"]:
        raise ValueError("expected logger header timestamp_ms,adc_count")
    rows = []
    for row in reader:
        if cancelled():
            raise InterruptedError("pressure log import cancelled")
        tick, count = int(row["timestamp_ms"]), int(row["adc_count"])
        if not rows:
            first_tick = tick
        if tick != first_tick + 20 * len(rows):
            raise ValueError("logger frame missing or out of order")
        if not 0 <= count <= 4095:
            raise ValueError("ADC reading outside 12-bit logger range")
        rows.append({"t": (tick - first_tick) / 1000, "adc_count": count, "pressure": (count - 50) * .05})
        if len(rows) == conditions["samples"]:
            break
    if len(rows) != conditions["samples"]:
        raise ValueError("export ends before the requested window")
    return rows


def metrics(uri, action, conditions, rows):
    if action != "ripple" or len(rows) != conditions["samples"]:
        raise ValueError("expected a complete pressure ripple window")
    for index, row in enumerate(rows):
        if row["t"] != (20 * index) / 1000 or row["pressure"] != (row["adc_count"] - 50) * .05:
            raise ValueError("pressure trace disagrees with the declared sample period or logger scale")
    pressures = [row["pressure"] for row in rows]
    return {"peak_to_peak_kpa": max(pressures) - min(pressures), "mean_kpa": fmean(pressures)}
