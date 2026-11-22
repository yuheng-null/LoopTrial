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

Repeat `--condition`, `--goal` and `--constraint` for additional fields. Bounds accept `le` and `ge`. Use `--note` for the reason behind a candidate or threshold. A completed measurement can miss its goal. Read `passed` for the verdict (true or false), or null for a measurement without criteria. CLI `run` and `status` return exit code 1 for a failed or cancelled run, and 0 for a completed measurement. Invalid arguments or an operation error return 2. MCP operation errors include `error.code`.

### Background runs and retries

```powershell
$job = looptrial run sim://thermal step --background --pace 4 --key demo-step | ConvertFrom-Json
looptrial status $job.id
```

The simulator's `--pace 4` adds four seconds of wall-clock delay before capture. Poll `status` for the terminal result. After `cancel`, poll again to confirm the final state. Retrying an identical request with its original key returns the existing run ID. For an independent confirmation, omit the key or use a new one.

The Blue Pill applies parameters in RAM until reset. Simulators retain effective settings in the current `LOOPTRIAL_HOME`. Set a new data directory to start from simulator defaults. After a link failure, inspect the run's `device_state` and write receipts for the last confirmed values.

### First MCP session

Register the installed `looptrial-mcp` executable in your client's stdio configuration. A typical entry is shown below. For a GUI client, use the full executable path if its PATH differs from your shell, and set `LOOPTRIAL_HOME` to the same absolute directory as the CLI.

```json
{
  "mcpServers": {
    "looptrial": {
      "command": "looptrial-mcp",
      "args": []
    }
  }
}
```

`looptrial-client` starts a local server, discovers tools, runs a thermal experiment and retrieves the result. To request a single tool call, use `looptrial-client --tool describe --arguments device.json` with a UTF-8 JSON file containing `{"uri":"sim://thermal"}`.
