# Reproduce a YALI whole-car experiment

[简体中文](RACE.md) · **English**

`race://yali` connects the YALI vision pipeline, cascaded controller and differential-drive plant to LoopTrial. Every trial starts from rest and renders the camera from the vehicle's evolving pose on an original marked course. The upstream revision is [a7237f9](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d). The two ovals are public test fixtures. Official competition routes may differ.

## First lap

Install the host wheel and have Edge or a Chromium-based browser with WebGL available. On Windows the backend checks standard install locations. Elsewhere set `LOOPTRIAL_BROWSER` to the browser executable's full path if discovery fails. The page, renderer and algorithms ship in the package. A temporary local HTTP server and isolated headless browser run the trial offline. Reviewing a saved CSV requires no browser.

```powershell
looptrial describe race://yali
$saved = (looptrial read race://yali | ConvertFrom-Json).verified
$b = looptrial run race://yali lap --condition course=1 --constraint valid_lap:ge:1 | ConvertFrom-Json
looptrial apply race://yali drive_speed=320
$c = looptrial run race://yali lap --condition course=1 --constraint valid_lap:ge:1 | ConvertFrom-Json
looptrial compare $b.id $c.id
looptrial review $c.id
looptrial apply race://yali "drive_speed=$($saved.drive_speed)"
```

A fresh store defaults to a wheel request of 250 model encoder units per second and `steer_gain` of 10.85 °/s/px. Reset recreates the controller and plant at rest at the same start. The `seed` initializes gyro noise. Use a fresh seed for independent confirmation, or `--condition course=2` for tighter turns. Submit with `--background` and use `status` or `cancel` from another process. A cancelled run retains the prefix already received by the host.

## How a valid finish is scored

- Each route combines two 1.30 m straights with semicircular turns. Turn radii are 0.85 m on the wide oval (`course=1`) and 0.62 m on the compact oval (`course=2`). The painted line is 6.5 cm wide. The vehicle starts midway along the left straight, facing negative Z. Its centre must remain within the legal corridor, by default 5.5 cm from the marked centreline throughout. Set `lane_half_width_m` to specify that limit.
- Eight finite-width checkpoint gates are spaced equally along the route. The eighth is the start/finish. The judge intersects the segment between consecutive samples with each directed gate. Resetting on the finish line does not count. A valid lap requires remaining in bounds, crossing all eight gates in order and in the forward direction, and reaching the finish by the timeout. The corridor also rules out shortcuts through turns.
- `samples.csv` records model time, position in metres, heading, speed, visual error, valid image rows, PWM, lateral deviation, ordered gate count and event every 10 ms. `event` codes are 0 running, 1 checkpoint, 2 finished, 3 outside the corridor (including cutting a corner), 4 missed/out-of-order gate, 5 timeout, 6 reverse crossing. `review` recomputes intersections, checks pose increments against speed and heading, and recalculates the verdict from the trajectory.
- `lap_time_s` is elapsed model time to termination and is a lap time only for a valid finish. `bend_time_s` counts time the chassis centre spends in the two semicircular ends. `max_offset_m` measures line-following margin as speed rises. Time thresholds on lap or bend time automatically require a valid lap. An early stop at the first bend cannot qualify as an improvement.

## Work to integrate an existing whole-car project

| What to locate in the existing project | Mapping used here |
| --- | --- |
| Action and observations | The original `processVisionAndControl_M2` and `createCircuitTrack` connect the image-track plane to a 188×120 WebGL camera with a 120° horizontal field of view. The original `runVision` extracts error from the pixels. `createController(...).update10ms` sets wheel PWM, and `createPlant(...).step` provides the wheel response, gyro and pose increments. |
| Settings and units | `drive_speed` maps to `params.diff.base_speed`. `steer_gain` maps to `steer.kp`. The former uses model encoder units. A physical encoder needs calibration before conversion to actual wheel speed. Every trial loads the effective host simulation settings into the fresh controller. |
| Adapter and scoring | `race_assets/lap.js` connects seven unchanged upstream modules using the original camera geometry, timing, feedback delays and pose integration. The original image-plane scale is used for the hand-drawn track. `race.py` describes capabilities, launches the browser and independently judges the recorded trajectory. CLI and MCP use the same backend. The controller receives no judge coordinates or checkpoint targets. |
| Observed effort | Prior work had exercised the isolated upstream speed loop through a small adapter. For the first whole-car integration, workstation timestamps put creation of the working checkout to the first reviewable full trajectory at about 3 min 38 s, including the first trial. That prototype recorded 858 samples. The figure excludes prior research and subsequent course calibration, scoring, process cleanup, testing, licensing and packaging. No upstream checkout edits were needed. |

The camera samples every 20 ms of model time, the controller updates every 10 ms and the wheel plant integrates every 1 ms. Vision feedback has a 30 ms delay and encoder feedback a 10 ms delay. The host receives batches of 25 control periods as fast as the browser and computer run. Lap times, changes and dynamics here are simulation results. Transfer to a physical vehicle requires measuring encoder scales, grip, load, camera position and latency, as well as independent on-track finish verification.

The seven upstream algorithm files and Three.js r128 retain their MIT notices. The renderer loads from the wheel without upstream competition images, logos or preset maps. [Upstream core](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d/core) · [Three.js r128 source](https://github.com/mrdoob/three.js/tree/r128) · [Third-party notices](../THIRD_PARTY.md)
