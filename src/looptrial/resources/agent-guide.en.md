# Run bench experiments with your agent

[简体中文](agent-guide.md) · **English**

Recover the symptom, operating conditions, target device and any write authorization from the conversation. Use tool discovery on an existing MCP connection, or use the CLI from a shell. From a clone, run `python -m pip install .` at the repository root in a Python 3.11+ virtual environment. To install the release wheel, follow the [project README](https://github.com/yuheng-null/LoopTrial/blob/main/README.en.md). Set `LOOPTRIAL_HOME` to choose where records go.

| First capture | CLI | Connected MCP client |
| --- | --- | --- |
| Find devices | `looptrial devices` | `devices` with `{}` |
| Inspect signals, units, actions and ranges | `looptrial describe sim://sensor` | `describe` with `{"uri":"sim://sensor"}` |
| Capture a pressure trace | `looptrial run sim://sensor capture` | `run_experiment` with `{"uri":"sim://sensor","action":"capture"}` |
| Recalculate from raw samples | `looptrial review <id>` with the returned ID | `review` with `{"record":"<id>"}`, substituting the returned ID |

If the user asks about noise at rest, one capture can answer the question. Report the conditions, noise metric and unit, and run ID. Identify results from a simulator as such. For a tuning request, continue as follows.

1. Read effective settings. Capture a baseline under the user's operating conditions from a repeatable initial state. Use source, device capabilities and baseline measurements to select an objective, hard constraints, comparison conditions, candidate budget and number of independent confirmations. Record the rationale in `note`.
2. Apply a candidate within the authorized range, check the independent readback, then capture a fresh trace under matching conditions. Use the waveform and constraints to decide whether to continue. Reuse the same `key` to retry a request. Omit it or use a fresh key for independent confirmation.
3. Confirm a passing candidate in a new run. To attribute a failure to saturation, report the output limit, time spent there and remaining target error. When the budget expires, state the range explored. Read back any restored settings. After a disconnect, repeat the handshake and read the configuration. Distinguish the last confirmed state from any current uncertainty. Cite each run ID that supports the conclusion.

When comparing event times, check `unavailable_delta`. For each listed metric, report which run observed the event and the observation window. An exact time saving requires a measured crossing in both runs.

[PowerShell quick start](quickstart.md) · [MCP configuration template](mcp-config.json)

When the workbench is open, use the same absolute `LOOPTRIAL_HOME` for the CLI and stdio MCP. Inspect `looptrial live` or `session_status` for the selected device and most recent confirmed state. Use `session_timeline` to identify manual or other client changes. CLI and MCP can also operate headlessly. The `lap` action on `race://yali` uses a rendered camera, model controllers and eight ordered checkpoints. Require a valid finish, optimize elapsed time and confirm with fresh runs.
