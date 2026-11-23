"""Exercise the installed workbench in Chromium. Development dependency: playwright.

python tests/workbench_browser.py --server-python /path/to/tested/python --out /new/output
Use --browser /path/to/edge-or-chrome if Playwright Chromium is not installed.
The test writes all records and screenshots below --out.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright


def wait_for_cli(predicate, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = predicate()
        if value:
            return value
        time.sleep(.15)
    raise AssertionError("Expected CLI state did not appear")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--browser")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    lab = out / "lab"
    if lab.exists():
        parser.error("Choose an output directory without a previous lab")
    env = dict(os.environ, LOOPTRIAL_HOME=str(lab), PYTHONUTF8="1")

    def invoke(module, *arguments, allow_cancel=False):
        result = subprocess.run(
            [args.server_python, "-m", "looptrial." + module, *arguments],
            cwd=out, env=env, capture_output=True, encoding="utf-8", timeout=30
        )
        if result.returncode and not (allow_cancel and result.returncode == 1):
            raise RuntimeError(result.stderr or result.stdout)
        return json.loads(result.stdout)

    def cli(*arguments, **kwargs):
        return invoke("cli", *arguments, **kwargs)

    def completed():
        return [r["id"] for r in cli("records") if r["status"] == "completed"]

    server = subprocess.Popen(
        [args.server_python, "-m", "looptrial.studio", "--no-browser"],
        cwd=out, env=env, stdout=subprocess.PIPE, encoding="utf-8"
    )
    try:
        url = json.loads(server.stdout.readline())["url"]
        summary = {}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            summary["browser"] = browser.version
            page = browser.new_page(viewport={"width":1400,"height":935}, locale="zh-CN",
                                    device_scale_factor=1, reduced_motion="reduce")
            page.set_default_timeout(12000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            assert page.evaluate("""async () => {
                const {tickLabel} = await import('./plot.js');
                return tickLabel(10000, .625) !== tickLabel(10000.625, .625)
                    && tickLabel(101325.1, .01) !== tickLabel(101325.11, .01);
            }""")
            page.locator("#choose-device").click()
            page.locator("#devices button", has_text="sim://sensor").click()
            page.locator("#connect").click()
            page.wait_for_selector("#connection-badge.on")
            wait_for_cli(lambda: "50" in page.locator("#sample-rate").inner_text())
            # Keep operator drafts intact across language changes and incoming snapshots.
            page.locator("#param-alpha").fill("0.42")
            page.locator("#conditions summary").click()
            condition = page.locator("#condition-seed")
            seed = condition.input_value()
            condition.fill("34")
            page.locator("#language").click()
            assert page.locator("#param-alpha").input_value() == "0.42"
            assert condition.input_value() == "34"
            page.locator("#language").click()
            assert page.locator("#param-alpha").input_value() == "0.42"
            page.locator("#undo").click()
            assert page.locator("#param-alpha").input_value() == "1" and page.locator("#undo").is_hidden()
            condition.fill(seed)
            page.locator("#conditions summary").click()
            summary["language_preserved_drafts"] = True
            page.locator("#run").click()
            baseline = wait_for_cli(lambda: next(iter(completed()), None))
            page.locator("#param-alpha").fill("0.2")
            page.locator("#apply").click()
            wait_for_cli(lambda: "alpha=0.2" in page.locator("#events").inner_text())
            assert cli("read", "sim://sensor")["verified"]["alpha"] == .2
            page.locator("#run").click()
            candidate = wait_for_cli(lambda: next((r for r in completed() if r != baseline), None))
            wait_for_cli(lambda: page.locator("#events li").count() >= 7)
            wait_for_cli(lambda: cli("live")["stats"]["samples"] >= 240)
            summary.update(viewport=[1400,935], baseline=baseline, candidate=candidate,
                           human_write=cli("writes", "sim://sensor")[0]["state"])
            page.locator("#freeze").click()
            assert page.locator("#plot-state").inner_text() == "已冻结"
            before = page.locator("#live-plot canvas").evaluate("(canvas) => canvas.toDataURL()")
            time.sleep(.65)
            assert before == page.locator("#live-plot canvas").evaluate("(canvas) => canvas.toDataURL()")
            page.locator("#freeze").click()
            page.locator("#signals button", has_text="raw").click()
            assert page.locator("#signals button", has_text="raw").get_attribute("aria-pressed") == "false"
            page.locator("#signals button", has_text="raw").click()

            # An independent standard stdio MCP client writes while the original page stays open.
            request = out / "apply-arguments.json"
            request.write_text(json.dumps({"uri":"sim://sensor","values":{"alpha":.35}}), encoding="utf-8")
            applied = invoke("client", "--tool", "apply_parameters", "--arguments", str(request))
            assert applied["verified"]["alpha"] == .35
            wait_for_cli(lambda: page.locator("#param-alpha").input_value() == "0.35")
            timeline = cli("timeline", "sim://sensor")
            for actor in ("human", "mcp"):
                stages = [e["kind"] for e in timeline if e["actor"] == actor]
                for kind in ("sent", "applied", "verified"):
                    assert kind in stages, (actor, stages)
            summary["write_stages"] = {actor:[e["kind"] for e in timeline if e["actor"]==actor and e["kind"] in ("sent","applied","verified")] for actor in ("human","mcp")}
            page.locator("#actor-filter").select_option("mcp")
            assert set(page.locator("#events .actor").all_text_contents()) == {"MCP"}
            page.locator("#actor-filter").select_option("")
            wait_for_cli(lambda: int(page.locator("#live-plot").get_attribute("data-markers") or 0) > 0)
            assert page.locator("#alignment").is_visible()
            # At 50 Hz, 600 rows represent less than 12 seconds. The workbench
            # must retain the rest of its requested window as snapshots overlap.
            page.locator("#window").select_option("60")
            def visible_seconds():
                label = page.locator("#live-plot canvas").get_attribute("aria-label") or ""
                match = re.search(r"· ([\d.eE+-]+)–([\d.eE+-]+) s", label)
                return float(match[2]) - float(match[1]) if match else 0
            wait_for_cli(lambda: visible_seconds() > 13, timeout=18)
            summary["observed_history_seconds"] = visible_seconds()
            page.locator("#window").select_option("15")
            page.mouse.move(1,1)
            page.screenshot(path=str(out / "workbench.png"), animations="disabled")
            page.locator("#language").click()
            page.screenshot(path=str(out / "workbench.en.png"), animations="disabled")
            page.locator("#language").click()

            page.locator("#compare-tab").click()
            page.locator("#baseline").select_option(baseline)
            page.locator("#candidate").select_option(candidate)
            page.locator("#compare-button").click()
            page.wait_for_selector("#metrics-block:visible")
            assert "noise_std" in page.locator("#metrics").inner_text()
            assert "alpha" in page.locator("#changed-params").inner_text()
            assert len(page.locator("#overlay-signals button").all()) >= 2
            summary["metric_delta"] = cli("compare", baseline, candidate)["delta"]
            page.screenshot(path=str(out / "comparison.png"), animations="disabled")
            incompatible = cli("run","sim://sensor","capture","--condition","seed=29")["id"]
            page.locator("#refresh-runs").click()
            page.locator("#candidate").select_option(incompatible)
            page.locator("#compare-button").click()
            wait_for_cli(lambda: "incomparable" in page.locator("#compare-note").inner_text())
            assert not page.locator("#metrics-block").is_visible()
            summary["incompatible_overlay_refused"] = True

            page.locator("#live-tab").click()
            page.locator("#window").select_option("60")
            wait_for_cli(lambda: visible_seconds() >= 59.8, timeout=65)
            summary["full_window_seconds"] = visible_seconds()
            job = cli("run","sim://sensor","capture","--background","--pace","6")["id"]
            page.locator("#stop").click()
            wait_for_cli(lambda: cli("status",job,allow_cancel=True)["status"] == "cancelled")
            summary["cancelled_run"] = job
            page.locator("#disconnect").click()
            page.wait_for_selector("#connection-badge.warn")
            assert page.locator("#param-alpha").is_disabled()
            assert page.locator("#confirmed-at").inner_text()
            page.locator("#connect").click()
            page.wait_for_selector("#connection-badge.on")
            assert cli("read","sim://sensor")["verified"]["alpha"] == .35
            page.set_viewport_size({"width":390,"height":844})
            assert page.locator("#live-plot").bounding_box()["y"] < 240
            page.locator("#connection-badge").click()
            assert page.locator("#param-alpha").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.keyboard.press("Escape")
            assert page.locator("#device-sheet").is_hidden()
            mobile_job = cli("run","sim://sensor","capture","--background","--pace","6")["id"]
            page.wait_for_selector("#mobile-run.stoppable")
            page.locator("#mobile-run").click()
            wait_for_cli(lambda: cli("status",mobile_job,allow_cancel=True)["status"] == "cancelled")
            page.locator("#language").click()
            assert page.locator("html").get_attribute("lang") == "en"
            wait_for_cli(lambda: "50" in page.locator("#sample-rate").inner_text())
            page.wait_for_selector("#mobile-run:not(.stoppable):enabled")
            page.screenshot(path=str(out / "mobile.png"), animations="disabled")
            previous_ids = set(completed())
            page.locator("#mobile-run").click()
            mobile_capture = wait_for_cli(lambda: next((r for r in completed() if r not in previous_ids), None))
            page.set_viewport_size({"width":320,"height":640})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#connection-badge").click()
            assert page.locator("#device-uri").is_visible()
            page.locator("#close-sheet").click()
            summary.update(mobile_stop=mobile_job, mobile_capture=mobile_capture, actor_filter=True)
            summary.update(mobile_viewport=[390,844], horizontal_overflow=False,
                           disconnect_kept_last_confirmation=True, page_errors=errors)
            assert not errors, errors
            browser.close()
        (out / "browser-check.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(summary))
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
