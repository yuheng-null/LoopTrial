"""Independently grade the released YALI race archive using only Python's standard library.

Project positions onto the stadium centreline, unwrap distance travelled across the
start line, and detect directed changes of sector. The live judge uses gate-plane
intersection. The two implementations agree to a sample on the published traces.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def track_coordinate(x, z, radius, half):
    arc = math.pi * radius
    perimeter = 4 * half + 2 * arc
    if z < -half:
        s = half + radius * (math.atan2(z + half, x) + math.pi)
    elif z > half:
        s = 3 * half + arc + radius * math.atan2(z - half, x)
    elif x > 0:
        s = 2 * half + arc + z
    else:
        s = -z
    radial = math.hypot(x, z - min(half, max(-half, z)))
    return s % perimeter, abs(radial - radius)


def verify(zipfile_object, member):
    rec = json.loads(zipfile_object.read(member))
    data = zipfile_object.read(member.replace("record.json", "samples.csv"))
    check(hashlib.sha256(data).hexdigest() == rec["samples_sha256"], "CSV hash mismatch")
    rows = [{k:float(v) for k,v in row.items()} for row in csv.DictReader(io.StringIO(data.decode("utf-8")))]
    c = rec["conditions"]
    radius = {1:0.85, 2:0.62}[c["course"]]
    half = 0.65
    perimeter = 4 * half + 2 * math.pi * radius
    previous_phase = 0.0
    progress = 0.0
    offset_max = 0.0
    bend_ticks = 0
    gates = 0
    event = 0
    previous = (-radius, 0.0)
    for i,row in enumerate(rows, 1):
        x, z, yaw = row["x_m"], row["z_m"], row["yaw_rad"]
        check(event < 2 and row["t"] == i / 100, "time or terminal discontinuity")
        step = row["speed_m_s"] / 100
        predicted = previous[0] - math.sin(yaw)*step, previous[1] - math.cos(yaw)*step
        check(math.dist((x,z), predicted) < 1e-8, "discontinuous chassis motion")
        previous = (x,z)
        phase, offset = track_coordinate(x,z,radius,half)
        delta = (phase - previous_phase + perimeter/2) % perimeter - perimeter/2
        progress += delta
        previous_phase = phase
        next_sector = math.floor((progress + 1e-10) / (perimeter / 8))
        event = 0
        if offset > c["lane_half_width_m"]:
            event = 3
        elif next_sector < gates:
            event = 6
        elif next_sector > gates + 1:
            event = 4
        elif next_sector > gates:
            gates += 1
            event = 2 if gates == 8 else 1
        if event < 2 and row["t"] >= c["timeout_s"]:
            event = 5
        check(row["gate_count"] == gates and row["event"] == event, f"gate/event mismatch at {i}")
        check(math.isclose(offset, row["offset_m"], abs_tol=1e-8), "lateral offset mismatch")
        offset_max = max(offset_max, offset)
        bend_ticks += abs(z) > half
    check(len(rows) == rec["samples"] and event >= 2, "incomplete trial")
    derived = {"valid_lap": int(event == 2), "lap_time_s": len(rows)/100,
               "gates_passed": gates, "max_offset_m": offset_max, "stop_event": event,
               "bend_time_s": bend_ticks/100,
               "peak_pwm": max(max(abs(r["pwm_l"]), abs(r["pwm_r"])) for r in rows)}
    for k,v in derived.items():
        check(math.isclose(v, rec["metrics"][k], abs_tol=1e-8), f"metric mismatch for {k}")
    return rec["id"], derived


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    args = cli.parse_args()
    with zipfile.ZipFile(args.archive) as traces:
        members = sorted(n for n in traces.namelist() if n.endswith("/record.json"))
        check(members, "no records")
        for m in members:
            run_id, result = verify(traces, m)
            print(json.dumps({"id":run_id, **result}, ensure_ascii=False))
        print(f"Verified {len(members)} complete trajectories")


if __name__ == "__main__":
    main()
