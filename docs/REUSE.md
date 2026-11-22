# 开源复用入口

**简体中文** · [English](REUSE.en.md)

以下是立项时读过的源码或官方文档。优先试能替代当前工作的最小部件。选择依赖、复用一段代码或兼容现有协议均可；结合目标 MCU 资源、现有工程侵入程度和头两套示例决定。把最终采用的项目、版本和用途记在实际交付文档中。直接使用上游源码时保留其版权及许可证，复核对应文件和所带第三方组件。

| 需求 | 优先评估的现成实现 | 已知差异 |
| --- | --- | --- |
| 任意物理量的运行时测量与标定 | [Scrutiny Debugger](https://scrutinydebugger.com/guide-introduction.html) 有嵌入式端、可读写的运行时值、目标端触发采集和 Python SDK。 | 可作为已有 Scrutiny 固件的后端候选；先核对小 MCU 的 ROM/RAM 开销和当前传输支持。不要要求每个接入设备都运行完整调试栈。 |
| 跨领域实验、设备描述与记录 | [Bluesky 项目](https://github.com/bluesky/bluesky) 和 [RunEngine 的实验元数据](https://blueskyproject.io/bluesky/main/metadata.html)。 | 观察如何让同一实验指令适配不同设备，以及怎样把上下文随数据保留。小型 MCU 项目按需借鉴这些做法。 |
| STM32 通信、离线分析、在线工作流 | [Automatically-adjust-PID-parameters，立项参考版本](https://github.com/Zw-awa/Automatically-adjust-PID-parameters/tree/067191da1a17)。从 `core/serial_manager.py`、`core/analyzer.py` 和 MCU 集成示例入手。 | 有带应答的协议和 F103/G431 示例。默认板端样例控制软件对象；核心程序自有代码和 ST/Arm 示例依赖分别核对许可。 |
| 多车型描述、阶跃指标与适配器 | [DiCAR-LAB，立项参考版本](https://github.com/zhaoxc857/DiCar-LAB/tree/7f1743907a54)。查看 `CAR_LAB/vehicles`、`core/metrics.py`、`core/ble_transport.py`（后两者位于 `CAR_LAB` 下）。 | 已有 BLE、参数回读、速度与直立配置。先挑不依赖 Qt 事件循环的模块；速度环的一阶加延迟模型有明确的适用范围。 |
| BLE 与 STM32 平衡车的完整对照 | [robot-control-prompts 调参脚本](https://github.com/laigure/robot-control-prompts/blob/3d6e22195642/tools/ble_pid_autotune.py)。 | 使用 FFE0/FFE1，能运行多次试验并输出 JSON。初始增益写在脚本里，评分偏向静止直立，要从目标设备读取基线并按实验选择指标。 |
| 把已有 Agent 接进来 | [llm-pid-tuner 的独立 Skill](https://github.com/KINGSTON-115/llm-pid-tuner/tree/53343a46c47b/skills/pid-tuning)。 | 参考其单位、控制器公式、离线数据分析与复测流程；设备连接由外部工具提供。 |
| Agent 接口与可复核指标 | [AlphaHarness 的 MCP 实验接口](https://github.com/Alphabots-8810/AlphaHarness/tree/30892efab7b4)。 | 面向 FRC NetworkTables，自动整定演示使用模拟飞轮。此处作为接口设计参考。 |
| 波形查看与外部 MCP 对照 | [Serial Studio API](https://github.com/Serial-Studio/Serial-Studio/blob/master/doc/help/API-Reference.md)。 | 支持串口和 BLE 特征读写，适合人工观察或比较现有工具，使用者可以独立运行。 |
| 跨平台设备 I/O 与 MCP | [pySerial](https://pyserial.readthedocs.io/en/latest/)、[Bleak](https://bleak.readthedocs.io/en/stable/api/client.html)、[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。 | 若选择 Python，优先复用驱动、协议 SDK 和现有客户端。使用 BLE GATT 时要分别处理通知和写特征。 |
| 验证动作与真实模块 | [WPILib SysId 实验方法](https://docs.wpilib.org/en/stable/docs/software/advanced-controls/system-identification/creating-routine.html)；[BD-BT26 模块文档](https://botelvdong.com/courses/Modules/docs/bluetooth/Summary)。 | 可借鉴可重复的电机激励、数据记录和试验终止。BD-BT26 默认 MCU UART 为 9600 8N1，FFE0 服务下订阅 FFE1，写 FFE1 或 FFE2；吞吐率需按实际接入条件验证。 |
