# 0.2 whole-car tuning acceptance

[简体中文](ACCEPTANCE-0.2.md) · **English**

On 2026-11-23, three independent Codex CLI 0.167.2 conversations ran on Windows outside the development checkout. Each used the user's existing login, a candidate wheel installed in a virtual environment, standard stdio MCP and its own run directory. The environment identified the connected simulator `race://yali` and authorized operations on it. The user stated the operating condition, waited for an answer, then sent only “这辆车过弯太慢，帮我调快一点” (“The car is too slow through the turns. Speed it up.”). No further human input followed. The logs contain the original messages, visible replies and chronological tool calls and results. [Run IDs, parameters, conditions and checksums](../evidence/race-v02/index.json)

| Earlier condition | Actual tool arguments | Baseline | Outcome |
| --- | --- | --- | --- |
| Wide oval | All 10 runs used `course=1` and a 55 mm half-width | 5.50 s lap, 3.66 s in bends | Speed 440, steering gain 20. After the qualifying run at seed 17, fresh runs used seeds 29, 43 and 71. All 4 passed 8 gates in order and took 3.22 s per lap, 2.08–2.09 s in bends. [Wide conversation](../evidence/race-v02/wide.jsonl) |
| Compact oval | All 12 runs used `course=2` and a 55 mm half-width | 4.54 s lap, 2.70 s in bends | Speed 330, gain 17. After seed 17, independent confirmations used 29, 43, 71 and 101. All 5 laps took 3.44–3.45 s and 2.00–2.01 s in bends. [Compact conversation](../evidence/race-v02/tight.jsonl) |
| Wide oval, one-second observation limit | `course=1, timeout_s=1` | Timed out at 1 s with 1/8 gates | The agent explained that the window could not establish a complete lap and stopped. Independent readback after the session confirmed the original speed 250 and gain 10.85. [Stop conversation](../evidence/race-v02/short.jsonl) |

**Continuing after failure.** The compact baseline `8d7092efeca84e378bf72c8f018b14a5` passed every gate. The agent allowed at most 12 trials and reserved independent confirmations. Raising speed to 300 while retaining gain 10.85 caused `ff50e1b1873640848d61fb601c3f70e0` to deviate by 61.8 mm after gate 4, exceeding the 55 mm limit. The agent changed gain and the next run, `0dd2d13c4c9844a3b263a39d759bc540`, achieved a valid finish. It continued choosing candidates using the remaining failed and successful observations. On the wide course it also rejected an out-of-bounds candidate and restored the previous qualifying settings. The short-window stop is `af7553c08848427a859d10c7483b97cd`.

Only the earlier route changed between the wide and compact conversations. The final symptom, other requirements, device capabilities and initial settings matched. The agents chose metrics, budgets of up to 12 runs, candidates and new confirmation seeds, and used independent tools to read back effective settings. Results apply to these routes, corridor, model and trial budgets. Acquisition used the candidate wheel from `f326f20`, fingerprinted in the index. Subsequent work added live sample publication, interrupted prefixes and a pose-increment check. All records were reviewed again offline. The release assets identify the final distributed package.

## Review offline

The [23 original trajectory records and waveforms](../evidence/race-v02/records.zip) contain 7,146 model-time samples, 17 valid laps, 5 out-of-bounds trials and 1 timeout. Each ID folder contains `record.json`, `samples.csv` and `plot.svg`. Download the ZIP to the current directory. A machine with LoopTrial installed can review it without a browser or connected vehicle.

```powershell
Expand-Archive records.zip -DestinationPath checked-laps
looptrial review ./checked-laps/ff50e1b1873640848d61fb601c3f70e0
looptrial review ./checked-laps/af7553c08848427a859d10c7483b97cd
```

An [independent geometric evaluator](../examples/verify_yali_laps.py) uses only the Python standard library. From the source root run `python examples/verify_yali_laps.py evidence/race-v02/records.zip`. The online judge intersects motion segments with directed gate planes. The independent evaluator projects each position onto the centreline, unwraps distance travelled and detects changes of sector. Both methods agree on events, gate counts, times and deviations for every archived sample. A regression obscures the painted line from the camera while keeping the judge's geometry intact. This produces zero valid image rows and an out-of-bounds finish.

**Scope.** The whole car here runs in a host WebGL simulator. Its signals, physical settings and controllers are software. See the [v0.2 board bench report](../evidence/v02/board/README.en.md) for the on-board software plant, physical USB serial and BD-BT26 links. Physical smart-car performance and SRDP water performance require measurements on the corresponding vehicles. [Reproduction and integration costs](RACE.en.md)
