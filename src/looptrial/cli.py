"""Non-interactive CLI. All command results are JSON."""

import argparse
from importlib.metadata import distribution
from importlib.resources import files
import json
import sys

from . import __version__, engine


def pairs(items):
    output = {}
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep or not name or name in output:
            raise ValueError("use distinct name=number arguments")
        try:
            output[name] = int(raw)
        except ValueError:
            output[name] = float(raw)
    return output


def rules(items):
    output = {}
    for expression in items:
        name, op, value = expression.split(":")
        bounds = output.setdefault(name, {})
        if op in bounds:
            raise ValueError(f"duplicate bound {name}:{op}")
        bounds[op] = float(value)
    return output


def parser():
    cli = argparse.ArgumentParser(prog="looptrial", description="Discover a device, acquire a bounded run, and review its data offline. Outputs JSON.",
        epilog="For a tuning request: carry over conversation conditions, measure a baseline, choose measurable goals, constraints, a finite trial budget and confirmation count. Verify each change, inspect the trace, then keep, revise or restore. Confirm success with new run IDs. For diagnosis alone, capture without changing parameters.")
    cli.add_argument("--version", action="version", version=__version__)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list simulator URIs, serial candidates and BLE preset")
    for name, help_text in (("describe","discover identity, units, actions, metrics and bounds"),
                            ("read","read effective parameter values"), ("writes","inspect parameter write and recovery receipts")):
        commands.add_parser(name, help=help_text).add_argument("uri")
    apply = commands.add_parser("apply", help="write temporary parameters, then independently read back")
    apply.add_argument("uri")
    apply.add_argument("values", nargs="+", metavar="name=number")
    run = commands.add_parser("run", help="acquire one trace using currently effective parameters")
    run.add_argument("uri")
    run.add_argument("action", help="action name from describe")
    run.add_argument("--condition", action="append", default=[], metavar="name=number")
    for opt in ("--goal", "--constraint"):
        run.add_argument(opt, action="append", default=[], metavar="metric:le|ge:number")
    run.add_argument("--note", default="", help="record decision, authority and comparison conditions")
    run.add_argument("--key", help="reuse to retrieve the same request after a timeout; new key for a new confirmation")
    run.add_argument("--background", action="store_true", help="return a durable ID before completion")
    run.add_argument("--pace", type=float, default=0, help="simulator wall-time delay in seconds, 0..600")
    run.add_argument("--fault", choices=["sample_gap"], help="inject a simulated acquisition interruption")
    for name, desc in (("status","query a run by ID"),("cancel","request bounded cancellation")):
        commands.add_parser(name, help=desc).add_argument("id")
    commands.add_parser("records", help="list recent IDs").add_argument("--limit", type=int, default=20)
    commands.add_parser("review", help="verify CSV checksum and recompute metrics from ID, record directory or file").add_argument("record")
    compare = commands.add_parser("compare", help="verify two comparable records and compute metric deltas")
    compare.add_argument("first")
    compare.add_argument("second")
    wave = commands.add_parser("wave", help="read a finite slice of raw timestamped samples")
    wave.add_argument("record")
    wave.add_argument("--start", type=int, default=0)
    wave.add_argument("--count", type=int, default=8)
    commands.add_parser("resources", help="locate installed examples, client source and documentation")
    return cli


def dispatch(a):
    match a.command:
        case "devices": return engine.devices()
        case "describe": return engine.describe(a.uri)
        case "read": return engine.read_parameters(a.uri)
        case "apply": return engine.apply_parameters(a.uri, pairs(a.values))
        case "writes": return engine.writes(a.uri)
        case "run":
            return engine.run_experiment(a.uri, a.action, pairs(a.condition), rules(a.goal),
                                         rules(a.constraint), a.note, a.key, a.background, a.pace, a.fault)
        case "status": return engine.get_run(a.id)
        case "records": return engine.list_runs(a.limit)
        case "review": return engine.review(a.record)
        case "cancel": return engine.cancel_run(a.id)
        case "wave": return engine.waveform(a.record, a.start, a.count)
        case "compare": return engine.compare(a.first, a.second)
        case "resources":
            root = files("looptrial")
            dist = distribution("looptrial")
            guide = next((f.locate().resolve().parent for f in dist.files or [] if f.as_posix().endswith("share/looptrial/README.md")), None)
            return {"examples": str(root / "resources"), "installed_guide": str(guide) if guide else None,
                    "mcp_client_source": str(root / "client.py"),
                    "record_store": str(engine.home())}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    try:
        result = dispatch(args)
    except engine.OPERATION_ERRORS as error:
        print(json.dumps(engine.failure(error), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if isinstance(result, dict) and result.get("status") in ("failed", "cancelled") and args.command in ("run","status"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
