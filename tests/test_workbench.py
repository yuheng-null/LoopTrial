"""Exercise the normal browser HTTP, CLI and independent MCP entry points together."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    from looptrial import engine
    monkeypatch.setenv("LOOPTRIAL_HOME", str(tmp_path))
    env = dict(os.environ, PYTHONUTF8="1")
    process = subprocess.Popen([sys.executable, "-m", "looptrial.studio", "--no-browser"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    try:
        info = json.loads(process.stdout.readline())
        def post(name, data, origin=None):
            headers = {"Content-Type":"application/json", "X-LoopTrial":"1"}
            if origin:
                headers["Origin"] = origin
            req = Request(info["url"] + "api/" + name, json.dumps(data).encode(), headers=headers)
            with urlopen(req, timeout=10) as response:
                return json.load(response)
        def cli(*args):
            cmd = subprocess.run([sys.executable, "-m", "looptrial.cli", *args], check=True,
                                 capture_output=True, text=True, encoding="utf-8", env=env)
            return json.loads(cmd.stdout)
        yield post, cli
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_shared_session_and_parameter_provenance(workbench, tmp_path):
    post, cli = workbench
    uri = "sim://sensor"
    session = post("connect", {"uri":uri})
    assert session["last_confirmed"]["values"]["alpha"] == 1
    baseline = cli("run", uri, "capture")
    receipt = post("apply_parameters", {"uri":uri,"values":{"alpha":.25}})
    assert receipt["actor"] == "human"
    args = tmp_path / "arguments.json"
    args.write_text(json.dumps({"uri":uri,"action":"capture"}))
    raw = subprocess.check_output([sys.executable,"-m","looptrial.client","--tool","run_experiment",
                                   "--arguments",str(args)], encoding="utf-8")
    candidate = json.loads(raw)
    assert candidate["actor"] == "mcp" and candidate["last_parameter_write"]["actor"] == "human"
    comparison = cli("compare", baseline["id"], candidate["id"])
    assert comparison["changed_parameters"] == {"alpha":[1,.25]}
    assert comparison["delta"]["noise_std"] < 0
    snapshot = cli("live")
    assert snapshot["session_id"] == session["session_id"] and snapshot["stats"]["samples"] > 2
    assert [e["kind"] for e in snapshot["events"] if e["actor"] == "human"][-3:] == ["sent","applied","verified"]
    assert snapshot["last_confirmed"]["values"]["alpha"] == .25
    detached = post("disconnect", {})
    assert detached["state"] == "unknown" and detached["values"] is None and detached["last_confirmed"]
    again = post("connect", {"uri":uri})
    assert again["state"] == "verified" and again["session_id"] != session["session_id"]
    assert again["values"]["alpha"] == .25


def test_generated_mcp_config_shares_lab_from_an_unrelated_client(workbench, tmp_path, monkeypatch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    post, cli = workbench
    session = post("connect", {"uri":"sim://sensor"})
    config = cli("mcp-config")["mcpServers"]["looptrial"]
    assert Path(config["command"]).is_absolute()
    assert Path(config["env"]["LOOPTRIAL_HOME"]) == tmp_path
    monkeypatch.setenv("LOOPTRIAL_HOME", str(tmp_path / "different-lab"))
    async def read_status():
        async with stdio_client(StdioServerParameters(**config)) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                result = await client.call_tool("session_status", {})
                assert not result.isError
                return json.loads(result.content[0].text)
    assert asyncio.run(read_status())["session_id"] == session["session_id"]


def test_standalone_demo_preserves_busy_device_error(workbench):
    _, cli = workbench
    job = cli("run", "sim://thermal", "step", "--background", "--pace", "30")
    try:
        result = subprocess.run([sys.executable, "-m", "looptrial.client"], timeout=20,
                                capture_output=True, encoding="utf-8")
        assert result.returncode == 1
        assert json.loads(result.stdout)["error"]["code"] == "device_busy"
    finally:
        cli("cancel", job["id"])


def test_standalone_client_preserves_single_event_lists_and_rejects_list_errors(workbench, tmp_path):
    post, _ = workbench
    post("connect", {"uri":"sim://sensor"})
    path = tmp_path / "arguments.json"
    def call(tool, arguments):
        path.write_text(json.dumps(arguments), encoding="utf-8")
        return subprocess.run([sys.executable, "-m", "looptrial.client", "--tool", tool,
                               "--arguments", str(path)], capture_output=True, text=True)
    timeline = call("session_timeline", {"uri":"sim://sensor", "limit":1})
    assert timeline.returncode == 0 and json.loads(timeline.stdout)[0]["kind"] == "connected"
    error = call("list_runs", {"limit":0})
    assert error.returncode == 1 and json.loads(error.stdout)["ok"] is False


def test_stop_active_job_and_restrict_browser_inputs(workbench):
    post, cli = workbench
    uri = "sim://thermal"
    post("connect", {"uri":uri})
    trial = post("run_experiment", {"uri":uri, "action":"step", "pace":5, "background":True})
    assert cli("live")["active_run"] == trial["id"]
    with pytest.raises(HTTPError):
        post("apply_parameters", {"uri":uri,"values":{"kp":.02}})
    post("cancel_run", {"run_id":trial["id"]})
    end = time.monotonic()+10
    while time.monotonic()<end:
        result = post("get_run", {"run_id":trial["id"]})
        if result["status"] == "cancelled":
            break
        time.sleep(.1)
    assert result["status"] == "cancelled"
    with pytest.raises(HTTPError) as exc:
        post("review", {"record":"../another/path"})
    assert exc.value.code == 400
    with pytest.raises(HTTPError) as exc:
        post("disconnect", {}, origin="https://foreign.invalid")
    assert exc.value.code == 403


def test_detached_mcp_run_keeps_submitter_after_client_exit(tmp_path, monkeypatch):
    from looptrial import engine
    monkeypatch.setenv("LOOPTRIAL_HOME", str(tmp_path / "store"))
    uri = "sim://sensor"
    args = tmp_path / "request.json"
    args.write_text(json.dumps({"uri":uri, "action":"capture", "background":True, "pace":1}))
    reply = subprocess.check_output([sys.executable, "-m", "looptrial.client", "--tool",
                                     "run_experiment", "--arguments", str(args)], encoding="utf-8")
    run_id = json.loads(reply)["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = engine.get_run(run_id)
        if result["status"] == "completed":
            break
        time.sleep(.05)
    assert result["status"] == "completed" and result["actor"] == "mcp"
    events = [e for e in engine.timeline(uri) if e["details"].get("id") == run_id]
    assert [(e["kind"], e["actor"]) for e in events] == [("run_started","mcp"), ("run_completed","mcp")]
