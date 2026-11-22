# Third-party components

[简体中文](THIRD_PARTY.zh-CN.md) · **English**

LoopTrial source, example models, firmware authored in this repository and documentation are distributed under GPL-3.0-or-later. See the [license](LICENSE).

The host wheel declares dependencies. The installer obtains their own distributions with their upstream notices. Direct dependencies are the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT, server and independent stdio client), [pySerial](https://github.com/pyserial/pyserial) (BSD-3-Clause, UART), [Bleak](https://github.com/hbldh/bleak) (MIT, BLE GATT) and [filelock](https://github.com/tox-dev/filelock) (MIT in the tested release, interprocess exclusion). See the [release dependency snapshot](requirements/windows-py312.txt) for exact acceptance versions. Python and Arm GNU toolchain executables are provided by the user.

The design considered the projects listed in the [upstream design references](docs/REUSE.en.md). Bluesky's separation of experimental metadata and observations informed the portable record. The bundled simulators can run with a virtual clock and the board protocol fits a UART bridge. These components and the experiment store are implemented here. No upstream PID application, Bluesky runtime or Qt UI is bundled.

The Blue Pill example uses the documented STM32F103 register map directly. Its startup, linker script, protocol and board model are included in firmware/. The published ELF is linked freestanding without a vendor HAL or C runtime. The separately installable pressure adapter includes a copy of the GPL.
