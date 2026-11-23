# LoopTrial 0.2.2

[简体中文](RELEASE.md) · **English**

Download the files from the [v0.2.2 release](https://github.com/yuheng-null/LoopTrial/releases/tag/v0.2.2). The tag identifies the source used for the build. `SHA256SUMS.txt` lists the host wheel, source distribution, board BIN and ELF, and evidence archive. `release-audit.json` records the build commit, platform, installation outside the checkout, standard MCP calls and offline checks.

## Workbench 0.2.2

On narrow screens, open the connection and parameter sheet from the top bar and start or stop a trial from the bottom bar. Channels show their last displayed readings. The chart identifies a frozen view or an unknown device state. Operators can discard unsubmitted edits and switch language while editing parameters or trial conditions. The timeline can be filtered by Operator, CLI or MCP.

The browser merges overlapping batches from the same session and retains samples actually received in the last 60 seconds. A new session or a page reload starts accumulating again. The horizontal axis shows the observed interval and the trace breaks at missing sequence numbers.

## Host patch 0.2.1

The workbench supports parameter edits and bounded captures on legacy LT1 0.1.0 firmware. It checks parameters about once per second while idle and reports an unknown state if readback fails. Continuous telemetry requires board firmware 0.2.0. Detached MCP experiments retain their originating client. New runs find write receipts across USB and BLE by device instance, attributing a write only when the firmware version and effective values match. Earlier receipts remain available in parameter history.

This patch rebuilds and verifies the existing 0.2.0 firmware. Legacy compatibility was tested on the host protocol bench. Physical USB/BLE measurements come from 0.2.0 using the same board image. To upgrade, install the wheel shown in the README in the existing environment and reuse the experiment directory.

## Release files

| File | Purpose |
| --- | --- |
| looptrial-0.2.2-py3-none-any.whl | Host package for Python 3.11+. Installing it provides `looptrial`, `looptrial-studio`, `looptrial-mcp` and `looptrial-client`. The release was tested on Windows with CPython 3.12. The first installation fetches dependencies. |
| looptrial-0.2.2.tar.gz | Sources for the host and firmware, experiments, tests, dependency lists and licenses needed to rebuild. |
| looptrial-bluepill-0.2.0.bin, looptrial-bluepill-0.2.0.elf | Dual-UART example for the STM32F103C8T6 (Cortex-M3, 64 KiB Flash). The BIN starts at 0x08000000. |
| looptrial-evidence-0.2.2.zip | Public conversations, tool calls, raw CSVs, run records, plots and board test notes. Keep each CSV beside its `record.json` to review the run by ID. |

## Rebuild from source

Run the following in Windows PowerShell with Python 3.12 installed. The Blue Pill build needs GNU Arm Embedded GCC (14.3.1 for acceptance). Put `arm-none-eabi-gcc` on PATH or pass `--toolchain-bin <directory>` to the firmware build script. Transport fault regression tests also need a native `gcc` or `cc` on PATH to build the C protocol code as a host shared library.

```powershell
git clone --branch v0.2.2 --depth 1 https://github.com/yuheng-null/LoopTrial.git
cd LoopTrial
git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements/build.txt
.\.venv\Scripts\python -m pip install -c requirements/windows-py312.txt .
.\.venv\Scripts\python -m pytest -q -rs
$env:SOURCE_DATE_EPOCH = "1704067200"
.\.venv\Scripts\python -m build --no-isolation --outdir dist
.\.venv\Scripts\python firmware/build.py --output dist
Get-FileHash dist\*
```

The Windows CPython 3.12 runtime dependency snapshot is in `requirements/windows-py312.txt`. Other platforms resolve dependencies from `pyproject.toml`. `SOURCE_DATE_EPOCH` fixes the wheel packaging timestamp. Use the published checksums to check the actual downloads. Changes to the toolchain, extraction format or packaging software may change build output. The [README](../README.en.md) covers installation outside the checkout, MCP and offline review.

## Validation scope

- **Host simulations.** Sensor measurement, pressure calibration, a thermal process, wheel speed and small-angle balancing. The thermal model can restart from the same state. Sensor trials can reuse or change the noise seed. Simulated time and wall-clock time are measured separately. Thresholds apply to their stated conditions.
- **Recorded data.** The separately installable pressure logger adapter replays raw counts with an inspectable sample rate, unit mapping and peak-to-peak measurement. Supply the actual scale and reference standard for your CSV.
- **Blue Pill.** A first-order discrete model runs on the MCU. USB serial and BD-BT26 GATT share a firmware identity, RAM settings and a capture buffer of up to 64 samples. See the [hardware guide](HARDWARE.en.md) for physical connections, restoration and repeat trials.
- **Physical performance.** The bench comprised a development board and communications module. External motors, heaters, pressure sensors and two-wheel vehicles still need physical trials. Firmware driving real actuators must enforce action permissions, physical limits, independent timeouts and fallback behavior.
- **Concurrency and state.** Local locks and a catalog coordinate access within one `LOOPTRIAL_HOME`. Clients accessing the same board should share it. Writes over serial or BLE change RAM. Use the last valid reading to interpret interrupted trials, exhausted budgets and calibrations lacking an independent reference. Persistence across power cycles requires a device-specific action.
- **Platforms.** Release acceptance used Windows x64 and Python 3.12. Verify other OS, Python and device combinations with the corresponding backend tests.

Original models, host tools and example firmware are GPL-3.0-or-later. See the [third-party notices](../THIRD_PARTY.md) for dependencies and upstream references.

## Workbench and whole-car additions

`looptrial studio` runs the local workbench and owns the shared connection. Use the same data directory across UI, CLI and MCP. The wheel contains the browser interface, Three.js r128, pinned YALI algorithms and original test courses. Whole-car trials need an installed WebGL-capable Edge or Chromium browser. Set `LOOPTRIAL_BROWSER` for a custom executable. After dependency installation, simulations, plots and record review operate locally. See the [release acceptance report](ACCEPTANCE-0.2.en.md) and [physical link records](../evidence/v02/board/README.en.md).
