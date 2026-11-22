# 第三方组件

**简体中文** · [English](THIRD_PARTY.md)

LoopTrial 的源码、示例模型、本仓库编写的固件和文档按 GPL-3.0-or-later 分发。条款见 [LICENSE](LICENSE)。

主机 wheel 声明运行依赖，安装器从各自的上游发行包取得组件和许可声明。直接依赖包括提供服务端与独立 stdio 客户端的[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（MIT）、用于 UART 的 [pySerial](https://github.com/pyserial/pyserial)（BSD-3-Clause）、用于 BLE GATT 的 [Bleak](https://github.com/hbldh/bleak)（MIT），以及用于进程间互斥的 [filelock](https://github.com/tox-dev/filelock)（验收版本为 MIT）。验收所用具体版本见[依赖快照](requirements/windows-py312.txt)。Python 和 Arm GNU 工具链可执行程序由使用者提供。

设计时评估的项目列在[开源复用入口](docs/REUSE.md)。便携记录借鉴了 Bluesky 区分实验元数据和观测值的做法。随包模拟器可使用虚拟时钟，板端协议可通过 UART 桥接。这些组件与实验记录库均在本仓库实现。分发包不包含上游 PID 应用、Bluesky 运行时或 Qt 界面。

Blue Pill 示例直接使用公开的 STM32F103 寄存器映射。启动代码、链接脚本、协议和板内模型位于 `firmware/`。发布的 ELF 独立链接，无需厂商 HAL 和 C 运行库。可单独安装的压力传感器适配器附有 GPL 副本。
