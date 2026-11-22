# From a symptom to an experiment result

[简体中文](ACCEPTANCE.md) · **English**

On 2026-11-22, five independent Codex CLI 0.167.2 conversations ran on Windows with CPython 3.12.10 outside the project directory. Each used an installed LoopTrial 0.1.0 candidate wheel, a separate data directory and a standard stdio MCP server. In each conversation the user first supplied an operating condition or intended use, waited for a reply, then sent a single symptom. No further human input followed. The bench environment identified the connected simulator. Each JSONL file preserves user messages, the agent's visible decisions and application-level tool calls in order.

## Two runs to start with

**50 °C heater.** The first message established the heater's normal 50 °C operating point. The final message asked the agent to speed up warm-up. The agent inspected capabilities and effective gains, measured a cold-start baseline from 20 °C, and interpreted “faster” as a reduction of at least 10% in time to 95% of the requested rise. After measuring 60 s it chose a 54 s threshold, constraints based on baseline overshoot and final-window error, up to three candidates and two fresh confirmations. The device described its gain ranges and returned effective values after each write. [Original two-turn conversation, arguments and results](../evidence/sim/thermal50.jsonl)

| Run | Kp / Ki | Time to 48.5 °C | Max overshoot | Decision |
| --- | --- | ---: | ---: | --- |
| Baseline `333c3da46b2f4dacb2536985b6d0f89e` | .012 / .0005 | 60 s | .941 °C | Set the improvement target |
| Candidate 1 `121a77f96e1a418d9f0c96d955074dce` | .018 / .0005 | 66.5 s | 0 °C | Slower. Increase integral gain. |
| Candidate 2 `5d151589410848dba89117c6b42593ca` | .018 / .00075 | 41.5 s | 1.271 °C | Overshoot exceeded baseline. Reduce integral gain. |
| Candidate 3 `84c163cd4f684ee3b5bbbf45b03dfb7f` | .018 / .00065 | 47.5 s | .625 °C | Confirm in fresh trials |
| Cold starts `7ecfab0fea9e40fd953c59944d639d1f` and `bd747e7f12644248a6d572e62b215829` | .018 / .00065 | both 47.5 s | both .625 °C | All criteria passed. Retain the temporary settings. |

**Stopping at the drive limit.** The user had specified 150 rpm, at most 45% duty and the original load. The agent tested the default gains. In run `71adba40457e4b64b85cd4dcfd548dae` output stayed at 45% from 1.52 to 8 s. Final speed settled at 66.6 rpm, still 83.4 rpm below target. The agent ended the search and left Kp=.003 and Ki=.004 in effect. The simulated load and supply would require more drive headroom. A separate CLI client observed the same plateau in a 15 s window. [Conversation and stop decision](../evidence/sim/motorlimit.jsonl) · [Independent CLI repeat](../evidence/sim/detached-cli.jsonl)

## Changing earlier context or switching devices

| Independent conversation | Conditions actually sent and measured | Final settings and confirmation |
| --- | --- | --- |
| Only the operating point changed, from 50 °C to 62 °C. The final request was identical. | All six `step` calls used `target_c=62`, from 20 °C. The 95% point became 59.9 °C. The baseline took 60 s. | Two candidates failed. Kp=.035 and Ki=.0019 then gave 32.5 s and .877 °C overshoot on both fresh starts. [62 °C conversation](../evidence/sim/thermal62.jsonl) |
| Earlier context added a 10 s delay between heating and observed temperature rise at 50 °C. Same final request. | All six runs sent `delay_s=10`. Baseline overshoot was 2.649 °C. The first two candidates exceeded it at 2.867 and 2.672 °C. | With Kp=.023 and Ki=.0006, both fresh trials improved on 49.5 s to reach 30.5 s with 1.841 °C overshoot. [Delayed heater](../evidence/sim/thermal50delay.jsonl) |
| Earlier context established that a sensor tracked steps. The final request only asked to steady a jittery reading. | Baseline stationary standard deviation was .930 kPa. The agent chose a .45 kPa limit and .25 s maximum 90% step delay. It paired inputs, allowed three candidates and reserved two new seeds for confirmation. | α changed from 1 to .20. On the paired input, noise fell to .316 kPa with .20 s delay. Fresh seeds 23 and 41 gave .385/.397 kPa, both with .16 s delay. [Sensor conversation](../evidence/sim/filter.jsonl) |

Each thermal agent selected its own percentage target from the baseline. A separate sensor client held the thresholds and candidate rule constant and varied only the noise. Both runs required standard deviation ≤.45 kPa, delay ≤.36 s and sustained arrival at the step target. At 1 kPa input noise, α=.274625 passed. At 1.35 kPa input noise that candidate measured .504 kPa. The client continued to α=.17850625, which passed both independent confirmations. [Tool calls for the matched targets](../evidence/sim/repeat-bench.jsonl)

## Calibration, interrupted acquisition and other examples

- **Held-out reference.** Fifty measurements at each of 5 and 35 kPa gave scale=.924621 and offset=−.711422 kPa. The held-out reference was 19 kPa. The original error was +2.2623 kPa. After applying the fit and using a fresh seed, the measured residual was +.0345 kPa. Runs `5ff8787fd7474ce2b9aaeee637a26575` and `42d6c66e96104c268652ddd057fed82a`.
- **Interrupted capture.** After baseline `416c354f238546c38be5b83f82cc43e5` the client wrote α=.3. Injected interruption `ffb0ae23c55849e3b5c0b55c28b076aa` retained 200/401 samples, too few for a full comparison. The client ended the trial, restored and read back α=1, scale=1 and offset=0. The baseline remained the last valid verdict. Offline review checks the truncated file's hash and reports `sample_gap`.
- **Wheel speed and two-wheel balance.** A 90 rpm step under normal load improved from 5.14 s to 3.52 s to reach 95%, still above the 2 s threshold. The next candidate and both confirmations took 1.86 s. After a 3° disturbance, balance run `053d4d79c75844e4b21d17f7e8556472` recovered in 1.6 s, with .0923 m maximum axle displacement and 1.021 m/s² peak acceleration. [Independent standard MCP calls and decisions](../evidence/sim/repeat-bench.jsonl)
- **Retrieve after leaving.** A CLI process submitted a background thermal step and exited. A second process used the same key and received the original ID `eb382cc9e77646c9a1d87ef772150e0b`. Later processes found the completed trial, retrieved 361 samples and recalculated its metrics offline. A 4 s wait modeled elapsed wall time. The waveform covered 180 s of model time. [CLI arguments, IDs and responses](../evidence/sim/detached-cli.jsonl)

## Review the data yourself

Install LoopTrial and obtain `evidence/sim/records.zip` from the source or evidence archive. The commands below need only the portable records. They work without hardware, the development workstation, the acquisition database or a model account. Copy any ID from the index. [Case and run index](../evidence/sim/index.json) · [All 49 raw records](../evidence/sim/records.zip)

```sh
python -m zipfile -e evidence/sim/records.zip bench-replay
looptrial review bench-replay/runs/bd747e7f12644248a6d572e62b215829
looptrial review bench-replay/runs/71adba40457e4b64b85cd4dcfd548dae
looptrial wave bench-replay/runs/71adba40457e4b64b85cd4dcfd548dae --start 390 --count 8
```

Each directory contains timestamped `samples.csv`, `record.json` with units, conditions, effective parameters, verdict and SHA-256, and `plot.svg`. Outside the checkout, a candidate package recalculated all 48 complete runs from CSV and verified the hash and row count of the one expected interruption. Looking directly in the CSVs for the first sample at or above ambient + 0.95 × requested rise independently matched all 18 reported rise times across the three heater conversations. To repeat calibration, wheel speed, balance, interruption, paired-noise and asynchronous CLI trials, run the following from the source with new output directories. [Executable examples](../examples/repeat_bench.py)

```sh
python examples/repeat_bench.py repeat-01
```

## Scope of the records

All five conversations used host simulator version 1.0. Separate cold starts of the deterministic thermal model may yield identical samples. The sensor confirmations used new seeds. Physical sensor calibration needs independent standards, and a real plant's load, delay, thermal capacity and noise require measurements. [Blue Pill physical bench and integration](HARDWARE.en.md)

The Codex acceptance sessions used an existing ChatGPT login. Each process was configured with the installed `looptrial-mcp`, its own `LOOPTRIAL_HOME` and process-level permission for the authorized simulator tools. An initial noninteractive connection attempt before that permission was configured ended without acquiring data. All five conversations were then started afresh. Public logs contain user messages, visible agent replies and LoopTrial inputs and outputs. Serial enumeration is redacted. Long waveform excerpts show the first and last samples, with full data in the run directories. The example Python client ran the fixed-rule regressions. The index records the candidate wheel fingerprint and Python module fingerprints at acquisition time. Checksums for the final release are in its assets. [Codex MCP configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
