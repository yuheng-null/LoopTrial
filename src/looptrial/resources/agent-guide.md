# 使用现有 Agent 做台架实验

**简体中文** · [English](agent-guide.en.md)

从对话里找出用户的症状、日常工况、目标设备和已有写入授权。已有 MCP 连接时直接发现工具；有终端时可以使用 CLI。克隆后在 Python 3.11+ 虚拟环境中从仓库根目录运行 `python -m pip install .`。也可以按[项目首页](https://github.com/yuheng-null/LoopTrial)安装发布包。数据目录由 `LOOPTRIAL_HOME` 指定。

| 第一次采样 | CLI | 已连接的 MCP 客户端 |
| --- | --- | --- |
| 找设备 | `looptrial devices` | `devices`，参数 `{}` |
| 看信号、单位、动作和范围 | `looptrial describe sim://sensor` | `describe`，参数 `{"uri":"sim://sensor"}` |
| 采一段压力波形 | `looptrial run sim://sensor capture` | `run_experiment`，参数 `{"uri":"sim://sensor","action":"capture"}` |
| 用原始数据复核 | `looptrial review <id>`，填入返回的编号 | `review`，参数 `{"record":"<id>"}`，填入返回的编号 |

如果用户只问静置时的噪声，这一次采样就能用来回答。报告测量工况、噪声指标及单位、实验编号；模拟器的读数只描述该模拟器。用户要调参时再进入后续步骤。

1. 读出生效配置，在用户工况和可重复的初态下采基线。结合源码、设备描述和基线选择目标、硬约束、可比条件、候选预算和独立确认次数，用 `note` 记录依据。
2. 在已授权范围内写入候选，检查独立回读，在相同工况下重新采样。根据波形和约束决定是否继续。重试同一请求时沿用 `key`，独立确认时省略它或使用新值。
3. 候选达标后另开一轮确认。若设备饱和，记录输出顶到哪个限值、持续多久以及目标与反馈的差距。预算用尽时说明已试范围；回退时读回生效值。断线后重新握手、读取配置，分清最后确认的状态和当前未知的状态。给出每项结论的实验编号。

比较达标时间时查看 `unavailable_delta`。对其中的指标说明哪轮观测到了目标事件，以及观察窗有多长。两轮都测到达标时刻，才能报告精确节省的时间。

[PowerShell 快速开始](quickstart.zh-CN.md) · [MCP 配置模板](mcp-config.json)

已打开工作台时，给 CLI 和 stdio MCP 使用同一绝对路径 `LOOPTRIAL_HOME`。先用 `looptrial live` 或 `session_status` 查看正在观察的设备和最后确认状态。可以用 `session_timeline` 检查用户或其他客户端的改动。若工作台未启动，CLI/MCP 仍可独立完成实验。整车对象 `race://yali` 的 `lap` 动作使用真实相机渲染、模型控制器和八个检查点；以有效完赛为硬条件，优化时间后用新试跑复验。
