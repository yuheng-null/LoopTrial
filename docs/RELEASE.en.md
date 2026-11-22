# LoopTrial 0.1.0

[简体中文](RELEASE.md) · **English**

Download the files from the [v0.1.0 release](https://github.com/yuheng-null/LoopTrial/releases/tag/v0.1.0). The tag identifies the source used for the build. `SHA256SUMS.txt` lists the host wheel, source distribution, board BIN and ELF, and evidence archive. `release-audit.json` records the build commit, platform, installation outside the checkout, standard MCP calls and offline checks.

## Release files

| File | Purpose |
| --- | --- |
| looptrial-0.1.0-py3-none-any.whl | Host package for Python 3.11+. Installing it provides `looptrial`, `looptrial-mcp` and `looptrial-client`. The release was tested on Windows with CPython 3.12. The first installation fetches dependencies. |
| looptrial-0.1.0.tar.gz | Sources for the host and firmware, experiments, tests, dependency lists and licenses needed to rebuild. |
| looptrial-bluepill-0.1.0.bin, looptrial-bluepill-0.1.0.elf | Dual-UART example for the STM32F103C8T6 (Cortex-M3, 64 KiB Flash). The BIN starts at 0x08000000. |
| looptrial-evidence-0.1.0.zip | Public conversations, tool calls, raw CSVs, run records, plots and board test notes. Keep each CSV beside its `record.json` to review the run by ID. |

## Rebuild from source

Run the following in Windows PowerShell with Python 3.12 installed. The Blue Pill build needs GNU Arm Embedded GCC (14.3.1 for acceptance). Put `arm-none-eabi-gcc` on PATH or pass `--toolchain-bin <directory>` to the firmware build script. Transport fault regression tests also need a native `gcc` or `cc` on PATH to build the C protocol code as a host shared library.

```powershell
git clone --branch v0.1.0 --depth 1 https://github.com/yuheng-null/LoopTrial.git
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
