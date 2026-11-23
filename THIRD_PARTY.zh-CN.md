# 第三方组件

**简体中文** · [English](THIRD_PARTY.md)

LoopTrial 的源码、示例模型、本仓库编写的固件和文档按 GPL-3.0-or-later 分发。条款见 [LICENSE](LICENSE)。

主机 wheel 声明运行依赖，安装器从各自的上游发行包取得组件和许可声明。直接依赖包括提供服务端与独立 stdio 客户端的[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（MIT）、用于 UART 的 [pySerial](https://github.com/pyserial/pyserial)（BSD-3-Clause）、用于 BLE GATT 的 [Bleak](https://github.com/hbldh/bleak)（MIT），以及用于进程间互斥的 [filelock](https://github.com/tox-dev/filelock)（验收版本为 MIT）。验收所用具体版本见[依赖快照](requirements/windows-py312.txt)。Python 和 Arm GNU 工具链可执行程序由使用者提供。

设计时评估的项目列在[开源复用入口](docs/REUSE.md)。便携记录借鉴了 Bluesky 区分实验元数据和观测值的做法。工作台、实验记录库、UART 协议及传感器、温控、轮速、直立模型均在本仓库实现。

Blue Pill 示例直接使用公开的 STM32F103 寄存器映射。启动代码、链接脚本、协议和板内模型位于 `firmware/`。发布的 ELF 独立链接，无需厂商 HAL 和 C 运行库。可单独安装的压力传感器适配器附有 GPL 副本。

## 随包整车软件

`looptrial/race_assets/upstream` 下七个 YALI 模块以及 `lap.js` 中改编的相机和位姿计算来自[雷霆之车 a7237f9](https://github.com/18439114865a-beep/leitingzhiche/tree/a7237f925f43aabab47ce10a30241184779a3b5d)，版权 © 2026 18439114865a-beep，采用 MIT 许可。随包的 [Three.js r128 渲染器及对应源码](https://github.com/mrdoob/three.js/tree/r128) 版权 © 2010–2021 three.js authors，采用 MIT 许可。两个组件的完整许可分别与各自的 JavaScript 一起分发。LoopTrial 的自绘赛道、裁判、工作台和接入代码采用 GPL-3.0-or-later。Edge/Chromium 由使用者另行安装。
