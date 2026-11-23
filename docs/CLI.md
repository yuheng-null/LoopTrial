# LoopTrial CLI & MCP

[简体中文](CLI.zh-CN.md) · **English**

The CLI prints JSON. MCP tools use the same device adapters and experiment store. Run `looptrial --help` for the CLI, `looptrial-client --list` for MCP tool schemas, and `looptrial resources` to locate the installed guides, example adapter, and MCP configuration template.

| Operation | CLI | MCP tool |
| --- | --- | --- |
| List available simulators, serial candidates and the BLE preset | `devices` | `devices` |
| Discover identity, signals, units, limits and actions | `describe URI` | `describe` |
| Read effective values | `read URI` | `read_parameters` |
| Write temporary values and read back | `apply URI name=value` | `apply_parameters` |
| Inspect write and restoration receipts | `writes URI` | `parameter_history` |
| Acquire one trace | `run URI ACTION` | `run_experiment` |
| Find runs, query status or request cancellation | `records`, `status ID`, `cancel ID` | `list_runs`, `get_run`, `cancel_run` |
| Read a slice of the raw trace | `wave ID --start 0 --count 8` | `waveform` |
| Verify a record and recalculate metrics | `review ID` or `review PATH` | `review` |
| Compare two runs under matching conditions | `compare FIRST SECOND` | `compare` |

### Conditions and verdicts

For a thermal step, this request specifies a 50 °C target, a warm-up time goal, and an overshoot limit. Parameter bounds and metric definitions come from `describe`.

```powershell
looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint overshoot_c:le:1
```

Repeat `--condition`, `--goal` and `--constraint` for additional fields. Bounds accept `le` and `ge`. Use `--note` for the reason behind a candidate or threshold. A completed measurement can miss its goal. Read `passed` for the verdict (true or false), or null for a measurement without criteria. CLI `run` and `status` return exit code 1 for a failed or cancelled run, and 0 for a completed measurement. Argument parsing and pre-submission errors return 2. A trial rejected by the device capability check after receiving an ID returns 1 and retains its failure record. MCP operation errors include `error.code`.

### Background runs and retries

```powershell
$job = looptrial run sim://thermal step --background --pace 4 --key demo-step | ConvertFrom-Json
looptrial status $job.id
```

The simulator's `--pace 4` adds four seconds of wall-clock delay before capture. Poll `status` for the terminal result. After `cancel`, poll again to confirm the final state. Retrying an identical request with its original key returns the existing run ID. For an independent confirmation, omit the key or use a new one.

The Blue Pill applies parameters in RAM until reset. Simulators retain effective settings in the current `LOOPTRIAL_HOME`. Set a new data directory to start from simulator defaults. After a link failure, inspect the run's `device_state` and write receipts for the last confirmed values.

### First MCP session

Run `looptrial mcp-config` in the environment used to start the workbench. Add the generated `mcpServers.looptrial` entry to the GUI client's stdio configuration. It includes the installed Python executable and the current lab's absolute path. To configure it manually, replace the example paths below.

```json
{
  "mcpServers": {
    "looptrial": {
      "command": "C:/LoopTrial/.venv/Scripts/python.exe",
      "args": ["-m", "looptrial.server"],
      "env": {"LOOPTRIAL_HOME": "C:/LoopTrial/lab"}
    }
  }
}
```

`looptrial-client` starts a local server, discovers tools, runs a thermal experiment and retrieves the result. To request a single tool call, use `looptrial-client --tool describe --arguments device.json` with a UTF-8 JSON file containing `{"uri":"sim://thermal"}`.

## Share an open workbench

Run `looptrial studio` to open the local workbench. It listens on loopback. Use `--no-browser` to open the printed URL manually or `--port` to select a port. Other terminals, agents and standalone MCP clients using the same absolute `LOOPTRIAL_HOME` delegate existing reads, writes, captures and cancellations to this process. Without the workbench, clients can still operate independently.

| Operation | CLI | MCP |
| --- | --- | --- |
| Select or switch the workbench device | `looptrial connect sim://sensor` | `session_connect` |
| Inspect connection, recent samples and confirmed state | `looptrial live` | `session_status` returns a compact summary |
| See who dispatched an operation and when it was acknowledged and confirmed | `looptrial timeline URI` | `session_timeline` |
| Inspect write receipts and dispatch-to-confirm milliseconds | `looptrial writes URI` | `parameter_history` |
| Close the link after active runs finish or stop | `looptrial disconnect` | `session_disconnect` |

Parameters can change during continuous observation. A bounded capture holds the device until completion and conflicting changes return `device_busy`. Compare completed, matched trials to inspect the changed parameters and each run's last writer. If multiple parameters changed, a difference alone cannot isolate one cause. Use new IDs for fresh confirmations. An invalid lap cannot enter a finish-time comparison. For an event time, read its numeric difference from `delta` only if both runs observed the event. Otherwise `unavailable_delta[metric]` names the event and supplies `first_observed` and `second_observed`. Other metrics can still be compared.

`sent` means the host dispatched a write to the adapter. `applied` reports the adapter's returned values. `verified` follows a matching independent read. Live batches carry a host arrival timestamp alongside the device or model sampling clock. On disconnect, the last confirmed values and time remain visible and current state becomes unknown. Reconnect repeats the handshake and effective readback. The service is designed for a trusted local bench with device-enforced limits.

On the four built-in control and sensor simulators, live preview advances continuously under default conditions and reflects parameter writes on the next sample. A bounded experiment resets the model and uses the conditions recorded for that run. Use the comparison view for these trial waveforms. In a YALI trial, the live trajectory comes directly from the graded run. On the Blue Pill, the continuous telemetry buffer and the bounded transient buffer each use their own acquisition timing.
