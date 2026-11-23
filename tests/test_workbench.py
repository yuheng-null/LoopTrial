"""Exercise the normal browser HTTP, CLI and independent MCP entry points together."""
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
