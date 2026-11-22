# Experiments across device types

[简体中文](EXPERIMENTS.md) · **English**

These PowerShell examples assume `looptrial` is installed. Each `run` starts an acquisition with the device's effective settings and returns a run ID. Simulators run on the host, and their sample timestamps use model time. Pass an ID to `review` to recalculate metrics from CSV or to `wave` to retrieve timestamped rows by index. Open the run's `plot.svg` in a browser.

Start with a new record directory to reproduce defaults. For ongoing work, keep the same `LOOPTRIAL_HOME` so CLI and MCP sessions share records and simulator settings.

```powershell
$env:LOOPTRIAL_HOME = Join-Path $PWD ("trials-" + [guid]::NewGuid())
looptrial devices
looptrial describe sim://thermal
looptrial read sim://thermal
```

## A heater takes too long to warm up

Recover the user's normal operating temperature first. For a 50 °C target, starting at 20 °C and observing for 180 s, `rise_s` measures time to the first sample at or above 48.5 °C, or 95% of the requested rise. Use rise time as the objective, with constraints on overshoot, final-window error and whether the target was reached. The limits below illustrate a choice. Base yours on the measured baseline, process tolerances and available trial budget.

```powershell
$t0 = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial apply sim://thermal kp=0.05 ki=0.0016
$t1 = looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint reached:ge:1 --constraint overshoot_c:le:1 --constraint steady_error_c:le:0.25 | ConvertFrom-Json
looptrial compare $t0.id $t1.id
looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint reached:ge:1 --constraint overshoot_c:le:1 --constraint steady_error_c:le:0.25
looptrial review $t1.id
```

Under the default conditions, the baseline rise time is 60 s and the candidate takes about 37.5 s. Each run starts at the same ambient temperature with an empty delay queue. The thermal time constant is 35 s. At full power the equilibrium temperature rise is 85 °C. `delay_s` controls when a change in duty reaches the plant. The controller uses PI with integrator limiting. When changing the operating temperature, check both `target_c` in the record and the target column in the samples. If `reached=0`, `rise_s` is the observation cutoff.

A long experiment can outlive the calling process. This example leaves a five-second wall-clock window before acquisition for checking status or requesting cancellation. A new shell using the same record directory can query the run ID.

```powershell
$job = looptrial run sim://thermal step --background --pace 5 | ConvertFrom-Json
looptrial status $job.id
Start-Sleep 6
looptrial status $job.id
```

## Sensor jitter and filter delay

A 50 Hz pressure source steps from 10 to 20 kPa at 3 s. Matching `seed` and `noise_std` values produce identical raw input. The noise metric is the population standard deviation of the filtered signal in the 1–3 s stationary window. Delay is measured to the first of three consecutive readings reaching 90% of the observed step amplitude. Both metrics use the same trace. For a diagnosis, inspect the raw and filtered columns after the first capture.

```powershell
$s0 = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial wave $s0.id --start 148 --count 8
looptrial apply sim://sensor alpha=0.25
$s1 = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial compare $s0.id $s1.id
looptrial run sim://sensor capture --condition seed=18 --goal noise_std:le:0.5 --constraint delay_s:le:0.30 --constraint reached:ge:1
```

On this input, reducing the current-sample weight from 1 to 0.25 reduces noise from about 0.930 to 0.355 kPa and increases delay from 0 to 0.14 s. Change the seed to test a fresh noise realization, or raise `noise_std` to check whether the settings still meet the requirements. Steady-state standard deviation measures repeatability. A physical delay measurement needs a stable baseline, a time-aligned reference step, matched sample rates and input conditions.

## Two-point calibration and a held-out third point

The same pressure device can take 50 readings at each of three known standards. Fit `reference = fit_scale × raw + fit_offset` to the low and high references, then measure the residual at the third. Here `raw` is the pressure in kPa using the nominal sensor scale, and `filtered` is the filtered reading. Calibration uses mean `raw`. An ADC adapter can expose raw counts and express the fitted scale in kPa/count.

```powershell
$c = looptrial run sim://sensor calibrate --condition ref_low=5 --condition ref_high=35 --condition ref_check=19 | ConvertFrom-Json
$c.metrics
looptrial apply sim://sensor "scale=$($c.metrics.fit_scale)" "offset=$($c.metrics.fit_offset)"
$check = looptrial run sim://sensor calibrate --condition seed=18 --condition ref_check=19 | ConvertFrom-Json
$check.metrics
looptrial review $check.id
```

`raw_residual` is the third-point error under the nominal scale. `fitted_residual` uses coefficients fitted in the current trial. `applied_residual` uses the coefficients effective on the device. With the initial scale of 1 and offset of 0, the applied and raw errors coincide. After writing the fit and repeating with a fresh seed, `applied_residual` independently tests the previous coefficients. Each record contains all three references, all samples and effective coefficients. Two points support an affine correction. If a physical calibration lacks independent traceable standards, retain the settings and report the missing reference.

## Motor tracking and drive saturation

The wheel starts from rest. The controller updates duty every 20 ms. Load is expressed as an equivalent fraction of full drive. The motor time constant is 0.42 s. At the default 90 rpm target, the baseline reaches 95% in about 5.14 s. An in-range candidate with `kp=0.012, ki=0.022` takes about 1.14 s.

```powershell
$m0 = looptrial run sim://motor step | ConvertFrom-Json
looptrial apply sim://motor kp=0.012 ki=0.022
$m1 = looptrial run sim://motor step --goal rise_s:le:2 --constraint reached:ge:1 --constraint overshoot_rpm:le:2 | ConvertFrom-Json
looptrial compare $m0.id $m1.id
looptrial run sim://motor step --goal rise_s:le:2 --constraint reached:ge:1 --constraint overshoot_rpm:le:2
$cap = looptrial run sim://motor step --condition target_rpm=180 --condition drive_limit=0.6 --goal reached:ge:1 | ConvertFrom-Json
$cap.metrics
looptrial wave $cap.id --start 391 --count 10
```

The final trial limits drive to 60% against an 8% opposing load. With a no-load full-drive speed of 180 rpm, the steady-state bound is `180 × (0.60 − 0.08) = 93.6 rpm`. Inspect the measured final speed, slope, duty and continuous saturation interval. Sustained maximum output with nearly constant speed supports ending the gain search under those conditions. Check the interval in the record to distinguish sustained saturation from a transient limit.

## Balancing after a disturbance

```powershell
$b = looptrial run sim://balance disturb --condition kick_deg=3 --goal recovery_s:le:2 --constraint recovered:ge:1 --constraint small_angle_valid:ge:1 --constraint max_drift_m:le:0.12 --constraint peak_output:le:4 | ConvertFrom-Json
$b.metrics
looptrial review $b.id
```

The small-angle inverted pendulum and horizontal axle use full-state feedback every 10 ms. A 3° tilt is applied at 0.5 s. The first fifty samples show the initial upright state. With a 0.25 m rod, `angular acceleration = (9.81 × tilt − axle acceleration) / 0.25`, with tilt in radians. The defaults return to and stay within ±0.2° in about 1.60 s after the disturbance. Maximum axle displacement is about 0.092 m and peak acceleration about 1.02 m/s². Constrain both drift and output when comparing candidates. If the tilt exceeds the model's ±12° linear range, `small_angle_valid=0`. End the performance assessment for that model.

## Integrate an existing pressure logger

The installed `resources/pressure_adapter` is a separately installable extension. It maps a 50 Hz logger's `timestamp_ms,adc_count` CSV to a read-only pressure device and adds a pressure variation experiment. Records store raw counts alongside relative seconds and nominal kPa so the scale and sample interval can be inspected. The backend registers through the `looptrial.devices` Python entry point and reuses the CLI, MCP server and record format.

Run the following in the activated Python environment. Eight synthetic rows in the original logger format are included to verify integration. Building this optional extension needs setuptools 77 or later. By default pip obtains it in an isolated build environment.

```powershell
$location = looptrial resources | ConvertFrom-Json
$adapter = Join-Path $location.examples pressure_adapter
Copy-Item -Recurse $adapter ./pressure_adapter
python -m pip install ./pressure_adapter
looptrial devices
looptrial describe pressure://fixture
$r = looptrial run pressure://fixture ripple --constraint peak_to_peak_kpa:le:0.5 | ConvertFrom-Json
looptrial review $r.id
```

The sample ranges from 499 to 507 count. The nominal conversion is `(count − 50) × 0.05 kPa`, yielding 0.4 kPa peak-to-peak. To use a different file in the same format, set `LOOPTRIAL_PRESSURE_LOG` to its absolute path. The adapter uses the file SHA-256 as input identity. The commands below require at least eight consecutive 20 ms samples. The adapter checks the input digest, period, 12-bit ADC range and window completeness. Offline `review` uses the saved rows and the installed metric implementation.

```powershell
$env:LOOPTRIAL_PRESSURE_LOG = (Resolve-Path ./export.csv).Path
$digest = (Get-FileHash $env:LOOPTRIAL_PRESSURE_LOG -Algorithm SHA256).Hash.ToLowerInvariant()
looptrial run "pressure://$digest" ripple --condition samples=8
```

To wrap another protocol, start with the three functions in `legacy_pressure.py`. Declare identity, version, units, actions and limits in `describe`. Implement `acquire` to turn a bounded window into device-timestamped raw samples. Implement `metrics` as a pure function for offline review. Use empty `parameters` for read-only devices. For writable devices implement `read(uri)` and `apply(uri, values)`, with `read` returning effective settings from the target. Update the adapter version when changing conversion or metric definitions. Replaying existing samples cannot predict the plant's response to a new controller setting.
