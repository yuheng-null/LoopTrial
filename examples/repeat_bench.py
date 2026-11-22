"""Run reproducible acceptance fixtures via an installed, independent MCP server.

Usage: python examples/repeat_bench.py NEW_OUTPUT_DIRECTORY
The directory holds calls.jsonl and a normal LoopTrial home for offline review.
"""

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class Bench:
    def __init__(self, session, log):
        self.session = session
        self.log = log

    def save(self, event):
        self.log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        self.log.flush()

    async def call(self, tool, **arguments):
        answer = await self.session.call_tool(tool, arguments)
        result = json.loads(answer.content[0].text)
        self.save({"tool": tool, "arguments": arguments, "result": result})
        if answer.isError or result.get("ok") is False:
            raise RuntimeError(f"{tool}: {result}")
        return result

    async def run(self, uri, action, **kwargs):
        return await self.call("run_experiment", uri=uri, action=action, **kwargs)

    async def apply(self, uri, values):
        await self.call("apply_parameters", uri=uri, values=values)
        read = await self.call("read_parameters", uri=uri)
        assert all(math.isclose(read["verified"][k], v) for k, v in values.items())
        return read["verified"]


async def wheel(bench):
    uri = "sim://motor"
    await bench.call("describe", uri=uri)
    initial = (await bench.call("read_parameters", uri=uri))["verified"]
    contract = dict(goals={"rise_s": {"le": 2.0}}, constraints={
        "reached": {"ge": 1}, "overshoot_rpm": {"le": 2},
        "steady_error_rpm": {"le": .5}})
    baseline = await bench.run(uri, "step", **contract)
    assert baseline["metrics"]["rise_s"] > 2
    # Discrete bounded search: a slow unsaturated step warrants more gain.
    # This fixed regression policy is separate from the live agent transcripts.
    for gains in ({"kp": .004, "ki": .006}, {"kp": .007, "ki": .012}):
        if baseline["metrics"]["saturation_fraction"] >= .9:
            raise RuntimeError("drive is saturated; gain search stopped")
        await bench.apply(uri, gains)
        baseline = await bench.run(uri, "step", **contract)
        if baseline["passed"]:
            break
    else:
        await bench.apply(uri, initial)
        raise RuntimeError("two-candidate budget exhausted")
    for _ in range(2):
        confirm = await bench.run(uri, "step", **contract)
        assert confirm["passed"]

    await bench.apply(uri, initial)
    conditions = {"target_rpm": 150, "drive_limit": .45, "duration_s": 15}
    # A trajectory at the drive ceiling with a flat, below-target plateau
    # distinguishes a power-limited stop from a controller that just needs time.
    limited = await bench.run(uri, "step", conditions=conditions,
                              goals={"reached": {"ge": 1}})
    m = limited["metrics"]
    assert m["reached"] == 0 and m["sat_longest_end_s"] == 15
    assert m["sat_longest_start_s"] < 5 and abs(m["tail_slope_rpm_s"]) < .01
    assert math.isclose(m["tail_output_mean"], conditions["drive_limit"])
    last = await bench.call("read_parameters", uri=uri)
    bench.save({"decision": "stop_at_output_ceiling", "run": limited["id"],
                "reason": "output stays at ceiling for the final 10 s or more, speed remains flat below target",
                "last_confirmed_parameters": last["verified"]})


async def sensor(bench):
    uri = "sim://sensor"
    await bench.call("describe", uri=uri)
    prior = (await bench.call("read_parameters", uri=uri))["verified"]
    first = await bench.run(uri, "calibrate")
    m = first["metrics"]
    await bench.apply(uri, {"scale": m["fit_scale"], "offset": m["fit_offset"]})
    confirm = await bench.run(uri, "calibrate", conditions={"seed": 29})
    residual = abs(confirm["metrics"]["applied_residual"])
    assert residual < .2 and residual < abs(first["metrics"]["applied_residual"])
    await bench.apply(uri, prior)

    good = await bench.run(uri, "capture")
    await bench.apply(uri, {"alpha": .3})
    broken = await bench.run(uri, "capture", fault="sample_gap",
                             goals={"noise_std": {"le": .45}})
    assert broken["status"] == "failed" and broken["samples"] < good["samples"]
    confirmed = await bench.apply(uri, prior)
    bench.save({"decision": "stop_on_incomplete_capture", "run": broken["id"],
                "last_valid_run": good["id"], "reason": "new candidate lacks a complete paired input",
                "restoration": "verified", "last_confirmed_parameters": confirmed})


async def compare_noise(bench):
    uri = "sim://sensor"
    baseline = (await bench.call("read_parameters", uri=uri))["verified"]
    contract = dict(goals={"noise_std": {"le": .45}},
                    constraints={"reached": {"ge": 1}, "delay_s": {"le": .36}})
    # Same limits and candidate rule in both sessions. Initial static noise
    # changes; the measured response determines when the search branches.
    for noise in (1, 1.35):
        await bench.apply(uri, baseline)
        alpha = baseline["alpha"]
        conditions = {"noise_std": noise, "seed": 17}
        response = await bench.run(uri, "capture", conditions=conditions, **contract)
        for _ in range(5):
            if response["passed"] or response["metrics"]["delay_s"] > .36:
                break
            alpha *= .65
            await bench.apply(uri, {"alpha": alpha})
            response = await bench.run(uri, "capture", conditions=conditions, **contract)
        if not response["passed"]:
            await bench.apply(uri, baseline)
            raise RuntimeError("noise-delay fixture stopped without a qualifying candidate")
        for seed in (18, 19):
            confirm = await bench.run(uri, "capture", conditions=conditions | {"seed": seed}, **contract)
            assert confirm["passed"]
        bench.save({"decision": "retain_after_two_new_noise_draws", "noise_condition": noise,
                    "search_run": response["id"], "accepted_alpha": alpha})
    await bench.apply(uri, baseline)


async def balance(bench):
    uri = "sim://balance"
    await bench.call("describe", uri=uri)
    response = await bench.run(uri, "disturb", conditions={"kick_deg": 3},
                               goals={"recovered": {"ge": 1}},
                               constraints={"small_angle_valid": {"ge": 1},
                                            "max_drift_m": {"le": .12},
                                            "peak_output": {"le": 4}})
    assert response["passed"]


def detached_step(output, env):
    cli = shutil.which("looptrial", path=str(Path(sys.executable).parent))
    with (output / "detached.jsonl").open("w", encoding="utf-8") as stream:
        def call(*args):
            result = subprocess.run([cli, *args], capture_output=True, text=True,
                                    check=True, env=env, encoding="utf-8")
            data = json.loads(result.stdout)
            stream.write(json.dumps({"argv": args, "result": data}) + "\n")
            return data

        # Each CLI process exits. The same key identifies the original step.
        args = ("run", "sim://thermal", "step", "--background", "--pace", "4",
                "--goal", "rise_s:le:65", "--constraint", "reached:ge:1",
                "--key", "detached-step")
        job = call(*args)
        assert job["status"] in ("queued", "running")
        assert call(*args)["id"] == job["id"]
        cutoff = time.monotonic() + 20
        while time.monotonic() < cutoff:
            status = call("status", job["id"])
            if status["status"] == "completed":
                assert status["passed"]
                assert call("review", job["id"])["recomputed"]
                break
            time.sleep(.5)
        else:
            raise RuntimeError("detached run did not complete")

        limited = call("run", "sim://motor", "step", "--condition", "target_rpm=150",
                       "--condition", "drive_limit=0.45", "--condition", "duration_s=15",
                       "--goal", "reached:ge:1")
        metrics = limited["metrics"]
        assert not limited["passed"] and metrics["sat_longest_end_s"] == 15
        assert math.isclose(metrics["tail_output_mean"], .45) and abs(metrics["tail_slope_rpm_s"]) < .01
        assert call("read", "sim://motor")["verified"] == limited["parameters"]
        stream.write(json.dumps({"decision": "stop_at_output_ceiling", "run": limited["id"],
                                 "last_confirmed_parameters": limited["parameters"]}) + "\n")


async def main(output):
    output.mkdir(parents=True, exist_ok=False)
    executable = shutil.which("looptrial-mcp", path=str(Path(sys.executable).parent))
    if not executable:
        raise SystemExit("Install LoopTrial in this Python environment first")
    env = dict(os.environ, LOOPTRIAL_HOME=str(output / "data"))
    server = StdioServerParameters(command=executable, env=env)
    async with stdio_client(server) as (rx, tx), ClientSession(rx, tx) as session:
        await session.initialize()
        with (output / "calls.jsonl").open("w", encoding="utf-8") as log:
            bench = Bench(session, log)
            bench.save({"tools": [t.name for t in (await session.list_tools()).tools]})
            await wheel(bench)
            await sensor(bench)
            await compare_noise(bench)
            await balance(bench)
    detached_step(output, env)
    print(f"Complete. Evidence: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    asyncio.run(main(parser.parse_args().output.resolve()))
