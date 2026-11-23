# Third-party components

[简体中文](THIRD_PARTY.zh-CN.md) · **English**

LoopTrial source, example models, firmware authored in this repository and documentation are distributed under GPL-3.0-or-later. See the [license](LICENSE).

The host wheel declares dependencies. The installer obtains their own distributions with their upstream notices. Direct dependencies are the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT, server and independent stdio client), [pySerial](https://github.com/pyserial/pyserial) (BSD-3-Clause, UART), [Bleak](https://github.com/hbldh/bleak) (MIT, BLE GATT) and [filelock](https://github.com/tox-dev/filelock) (MIT in the tested release, interprocess exclusion). See the [release dependency snapshot](requirements/windows-py312.txt) for exact acceptance versions. Python and Arm GNU toolchain executables are provided by the user.

The design considered the projects listed in the [upstream design references](docs/REUSE.en.md). Bluesky's separation of experimental metadata and observations informed the portable record. LoopTrial implements its workbench, experiment store, UART protocol and sensor, thermal, motor and balance models.

The Blue Pill example uses the documented STM32F103 register map directly. Its startup, linker script, protocol and board model are included in firmware/. The published ELF is linked freestanding without a vendor HAL or C runtime. The separately installable pressure adapter includes a copy of the GPL.

## Bundled race software

The seven YALI modules under `looptrial/race_assets/upstream` and the camera/odometry adaptation in `lap.js` derive from [leitingzhiche a7237f9](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d). Copyright © 2026 18439114865a-beep, MIT. The bundled [Three.js r128 renderer and its sources](https://github.com/mrdoob/three.js/tree/r128) are copyright © 2010–2021 three.js authors, MIT. Each distribution retains both full upstream license texts next to the respective JavaScript. The LoopTrial course markings, judge, workbench and integration use GPL-3.0-or-later. The included tracks are drawn for this release. Edge/Chromium runs as an external program supplied by the user.
