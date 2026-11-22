"""Portable record format. Reading a record never opens a device."""

import csv
import hashlib
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_rules(metrics, rules, requires_event=None):
    checks = []
    for name, bounds in rules.items():
        if name not in metrics:
            raise ValueError(f"unknown metric {name!r}; available: {', '.join(metrics)}")
        for op, limit in bounds.items():
            value = metrics[name]
            passed = value <= limit if op == "le" else value >= limit
            check = dict(metric=name, op=op, limit=limit, value=value, passed=passed)
            event = (requires_event or {}).get(name)
            if event and not metrics[event]:
                check.update(passed=False, reason=f"{event}=0; event time is censored")
            checks.append(check)
    return checks


def check_rows(rows):
    if len(rows) < 2:
        raise ValueError("at least two timestamped samples are required")
    keys = set(rows[0])
    if "t" not in keys or len(keys) < 2:
        raise ValueError("expected t and at least one signal")
    previous = -math.inf
    for row in rows:
        if set(row) != keys or not all(math.isfinite(v) for v in row.values()):
            raise ValueError("sample fields changed or contain nonfinite values")
        if row["t"] <= previous:
            raise ValueError("timestamps must increase strictly")
        previous = row["t"]


def write_samples(directory, rows):
    path = directory / "samples.csv"
    temp = directory / "samples.tmp"
    with temp.open("w", newline="", encoding="utf-8") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    temp.replace(path)
    return digest(path)


def saved_samples(directory):
    """Recover an existing acquisition after its worker exited between filesystem writes."""
    path = directory / "samples.csv"
    if not path.exists():
        return 0, write_samples(directory, [])
    with path.open(newline="", encoding="utf-8") as stream:
        count = sum(1 for _ in csv.DictReader(stream))
    return count, digest(path)


def load_samples(directory, record):
    path = directory / "samples.csv"
    if digest(path) != record["samples_sha256"]:
        raise ValueError("samples.csv SHA-256 differs from record")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if len(rows) != record["samples"]:
        raise ValueError("sample count differs from record")
    return rows


def plot(directory, rows, signals):
    """One axis per quantity, preserving units and relative time."""
    if len(rows) < 2:
        return
    fields = [k for k in rows[0] if k != "t"]
    span = rows[-1]["t"] - rows[0]["t"]
    if span <= 0:
        return
    width, height = 760, 144 * len(fields) + 46
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<g font-family="sans-serif" font-size="13" fill="#172c36">']
    for index, key in enumerate(fields):
        values = [r[key] for r in rows]
        low, high = min(values), max(values)
        y = 20 + 144 * index
        label = escape(f"{key} [{signals.get(key, {}).get('unit', '')}]")
        lines.extend([f'<text x="12" y="{y}">{label}</text>',
                      f'<text x="12" y="{y+25}">{high:.4g}</text>',
                      f'<text x="12" y="{y+110}">{low:.4g}</text>',
                      f'<rect x="86" y="{y+13}" width="650" height="100" fill="#eef4f6"/>'])
        points = []
        for row in rows:
            x = 86 + 650 * (row["t"] - rows[0]["t"]) / span
            offset = (row[key] - low) / (high - low) if high > low else 0.5
            points.append(f"{x:.2f},{y+113-100*offset:.2f}")
        lines.append(f'<polyline fill="none" stroke="#14798a" stroke-width="1.4" points="{" ".join(points)}"/>')
    lines.append(f'<text x="86" y="{height-14}">{rows[0]["t"]:.3g} s</text>')
    lines.append(f'<text x="680" y="{height-14}">{rows[-1]["t"]:.4g} s</text></g></svg>')
    (directory / "plot.svg").write_text("\n".join(lines), encoding="utf-8")
