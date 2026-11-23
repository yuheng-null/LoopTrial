"""Run an isolated YALI WebGL line-following trial and grade its recorded trajectory."""
import json
import math
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = Path(__file__).with_name("race_assets")
UPSTREAM = "a7237f925f43aabab47ce10a30241184779a3b5d"
# Camera/plant world units are 10 cm. Scoring uses metres.
COURSES = {1: (0.85, 0.65), 2: (0.62, 0.65)}
GATE_COUNT = 8
EVENTS = {0: "running", 1: "checkpoint", 2: "finish", 3: "off_course",
          4: "missed_checkpoint", 5: "timeout", 6: "reverse_crossing"}


def _browser():
    explicit = os.environ.get("LOOPTRIAL_BROWSER")
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise ValueError("LOOPTRIAL_BROWSER must be the path of a Chromium-based browser executable")
    for name in ("microsoft-edge", "chromium", "chromium-browser", "google-chrome"):
        if found := shutil.which(name):
            return found
    for root in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        for suffix in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            if (p := Path(os.environ.get(root, "missing")) / suffix).is_file():
                return str(p)
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if Path(p).is_file():
            return p
    raise ValueError("Install Edge or Chromium with WebGL, or set LOOPTRIAL_BROWSER to its executable")


def field(unit, description, **attributes):
    return dict(unit=unit, description=description, **attributes)


def describe(uri):
    if uri != "race://yali":
        raise ValueError("use race://yali")
    return {"id": "yali-whole-car", "version": "0.2.0+" + UPSTREAM[:8], "source": "simulation",
            "signals": {
                "t":field("s","Vehicle model time"), "x_m":field("m","World X from overhead survey"),
                "z_m":field("m","World Z from overhead survey"), "yaw_rad":field("rad","Vehicle heading"),
                "speed_m_s":field("m/s","Chassis speed"), "visual_error_px":field("px","Camera tracking error"),
                "visible_rows":field("rows","Valid image scanlines"), "pwm_l":field("PWM","Left drive"),
                "pwm_r":field("PWM","Right drive"), "offset_m":field("m","Distance to marked route centre"),
                "gate_count":field("gates","Ordered checkpoints reached including finish"),
                "event":field("code","; ".join(f"{k}={v}" for k,v in EVENTS.items()))},
            "parameters": {
                "drive_speed":field("enc/s","Drive speed request to the wheel controllers. Higher requests can leave the lane in bends.",
                                    default=250, min=60, max=440),
                "steer_gain":field("deg/s/px","Camera error to yaw-rate setpoint gain. Test under the same route and limits.",
                                    default=10.85,min=2,max=25)},
            "actions":{"lap":{"description":"Reset vehicle and controller, start from rest, follow the camera line through eight gates in order. Off-course/missed/reverse/timeout are terminal. A valid lap is required when comparing elapsed times.",
                               "sample_period_s":0.01,
                               "conditions":{
                                   "course":field("id","1=wide oval, 2=tight oval. Both are self-drawn closed circuits.", default=1,min=1,max=2,type="integer"),
                                   "lane_half_width_m":field("m","Maximum centre deviation for a legal lap. Shared user/track limit.",default=.055,min=.02,max=.30),
                                   "timeout_s":field("s","Maximum simulated time to finish, measured from reset.",default=25,min=1,max=40),
                                   "seed":field("seed","IMU noise seed for repeatable starts; use another seed for independent confirmation.",default=17,min=0,max=2**31-1,type="integer")},
                               "metrics":{
                                   "valid_lap":field("bool","1 only for a forward, in-order, in-bounds finish"),
                                   "lap_time_s":field("s","Elapsed model time. Censored for an invalid lap.",requires_event="valid_lap"),
                                   "max_offset_m":field("m","Largest centre-to-line distance"),
                                   "bend_time_s":field("s","Model time spent on the two semicircular ends; meaningful for complete laps.",requires_event="valid_lap"),
                                   "gates_passed":field("gates","Ordered gate count (8 for finish)"),
                                   "stop_event":field("code","Terminal event code; see event signal"),
                                   "peak_pwm":field("PWM","Maximum absolute wheel output")}}}}


def _gate(distance, radius, half):
    """Position and forward unit tangent on the clockwise stadium centreline."""
    straight = 2 * half
    arc = math.pi * radius
    # Start at the left tangent midpoint travelling toward negative Z.
    d = (distance + half) % (2 * straight + 2 * arc)
    if d < straight:
        return -radius, half - d, 0, -1
    d -= straight
    if d < arc:
        angle = math.pi + d / radius
        return radius*math.cos(angle), -half+radius*math.sin(angle), -math.sin(angle), math.cos(angle)
    d -= arc
    if d < straight:
        return radius, -half + d, 0, 1
    angle = (d - straight) / radius
    return radius*math.cos(angle), half+radius*math.sin(angle), -math.sin(angle), math.cos(angle)


class Judge:
    def __init__(self, conditions):
        self.radius, self.half = COURSES[conditions["course"]]
        circumference = 4*self.half + 2*math.pi*self.radius
        self.gates = [_gate(i*circumference/GATE_COUNT,self.radius,self.half) for i in range(1,GATE_COUNT+1)]
        # Define the reset/finish plane exactly: floating wrap at the full period must
        # not turn the first millimetre of a fresh start into a premature finish.
        self.gates[-1] = (-self.radius, 0.0, 0.0, -1.0)
        self.width = conditions["lane_half_width_m"]
        self.timeout = conditions["timeout_s"]
        self.previous = (-self.radius, 0.0)
        self.count = 0
        self.event = 0

    def observe(self, row):
        x, z = row["x_m"], row["z_m"]
        px, pz = self.previous
        offset = abs(math.hypot(x, max(0, abs(z)-self.half)) - self.radius)
        event = 0
        if offset > self.width:
            event = 3
        else:
            for i, (gx,gz,tx,tz) in enumerate(self.gates):
                before = (px-gx)*tx + (pz-gz)*tz
                after = (x-gx)*tx + (z-gz)*tz
                if not (before < 0 <= after or before > 0 >= after):
                    continue
                ratio = before/(before-after)
                cross_x, cross_z = px + ratio*(x-px), pz + ratio*(z-pz)
                if math.hypot(cross_x-gx, cross_z-gz) > self.width:
                    continue
                if after < before:
                    event = 6
                elif i != self.count:
                    event = 4
                else:
                    self.count += 1
                    event = 2 if self.count == GATE_COUNT else 1
                break
        if event < 2 and row["t"] >= self.timeout:
            event = 5
        self.previous = (x,z)
        self.event = event
        return {"gate_count":self.count, "offset_m":offset, "event":event}


def metrics(uri, action, conditions, rows):
    if action != "lap" or len(rows) < 2:
        raise ValueError("expected a whole-car lap trace")
    judge = Judge(conditions)
    for index, row in enumerate(rows, 1):
        if row["t"] != index/100 or judge.event >= 2:
            raise ValueError("trajectory timestamps or terminal position inconsistent")
        proof = judge.observe(row)
        if any(not math.isclose(row[key], value, abs_tol=1e-9) for key,value in proof.items()):
            raise ValueError("reported event disagrees with recorded trajectory")
    if judge.event < 2:
        raise ValueError("trajectory has no terminal event")
    return {"valid_lap":int(judge.event == 2), "lap_time_s":rows[-1]["t"], "gates_passed":judge.count,
            "bend_time_s":sum(abs(row["z_m"])>judge.half for row in rows)/100,
            "max_offset_m":max(row["offset_m"] for row in rows),"stop_event":judge.event,
            "peak_pwm":max(max(abs(row["pwm_l"]), abs(row["pwm_r"])) for row in rows)}


def acquire(uri, action, conditions, params, cancelled):
    if action != "lap":
        raise ValueError("race://yali supports lap")
    executable = _browser()
    judge = Judge(conditions)
    config = {"course":{"radius":judge.radius*10,"half_straight":judge.half*10}, "settings":params, "conditions":conditions}
    rows, errors = [], []
    prefix = "/" + secrets.token_urlsafe(24) + "/"
    files = {p.relative_to(ASSETS).as_posix(): p for p in ASSETS.rglob("*") if p.is_file()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def reply(self, data, mime="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == prefix + "config":
                self.reply(json.dumps(config).encode())
            elif path.startswith(prefix) and (file := files.get(path[len(prefix):])):
                mime = "application/javascript" if file.suffix == ".js" else mimetypes.guess_type(file.name)[0]
                self.reply(file.read_bytes(), mime or "application/octet-stream")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path not in (prefix+"frames",prefix+"error"):
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 65536:
                self.send_error(400)
                return
            raw = self.rfile.read(length)
            if self.path == prefix+"error":
                errors.append(raw.decode("utf-8","replace")[:500])
            else:
                for row in json.loads(raw):
                    row.update(judge.observe(row))
                    rows.append(row)
                    if judge.event >= 2:
                        break
            self.reply(json.dumps({"more":judge.event < 2 and not errors}).encode())

    with tempfile.TemporaryDirectory(prefix="yali-",ignore_cleanup_errors=True) as profile, ThreadingHTTPServer(("127.0.0.1",0),Handler) as http:
        http.timeout = .15
        port = http.server_address[1]
        args = [executable, "--headless", "--disable-extensions", "--disable-background-networking",
                "--disable-sync", "--no-first-run", "--no-default-browser-check","--no-proxy-server",
                "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--user-data-dir="+profile,
                f"http://127.0.0.1:{port}{prefix}track.html"]
        proc = subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            deadline = time.monotonic()+120
            while judge.event < 2 and not errors:
                if cancelled():
                    raise InterruptedError("Whole-car trial cancelled")
                if proc.poll() is not None or time.monotonic() >= deadline:
                    raise ValueError(f"Browser ended or timed out with {len(rows)} trajectory samples; check Chromium/WebGL")
                http.handle_request()
            if errors:
                raise ValueError("Race browser: "+errors[0])
        finally:
            if proc.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    return rows
