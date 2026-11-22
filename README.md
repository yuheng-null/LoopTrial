# LoopTrial

LoopTrial 让工程师和已有的 AI Agent 通过同一组 CLI / MCP 操作发现设备、采集波形、调整临时参数、回读生效值，并按实验编号复核结果。用户可以先告诉 Agent “平时工作在 50 °C”，随后只说“升温太慢，帮我调快一点”。设备能力给出可测信号、单位、可写范围和动作，Agent 根据对话与基线安排下一轮。工具本身可离线运行，无需模型账号。

**[下载 v0.1.0](https://github.com/yuheng-null/LoopTrial/releases/tag/v0.1.0)** · [自主调参与停止记录](docs/ACCEPTANCE.md) · [Blue Pill 接线、协议与实测](docs/HARDWARE.md) · [五类实验和新设备接入示例](docs/EXPERIMENTS.md)

## 第一次使用

在项目目录之外打开空目录。以下命令适用于 Windows PowerShell，先安装 Python 3.12 和 Python Launcher。联网安装依赖后，模拟、采集、MCP 和记录复核均在本机执行。将 Release 中的 `looptrial-0.1.0-py3-none-any.whl` 下载到当前目录。可用 `Get-FileHash .\looptrial-0.1.0-py3-none-any.whl` 对照同一发布页的 SHA256SUMS.txt。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install .\looptrial-0.1.0-py3-none-any.whl
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:LOOPTRIAL_HOME = "$PWD\lab"
looptrial describe sim://thermal
$r = looptrial run sim://thermal step --condition target_c=50 | ConvertFrom-Json
looptrial review $r.id
looptrial-client
```

温控默认基线从 20 °C 加热，361 个采样点覆盖 180 s 虚拟时间，达到阶跃幅度 95% 用时 60 s。最后一条命令启动独立标准 MCP 客户端和 stdio 服务进程。客户端发现工具后重新做一次实验，用返回的编号取回结果并离线重算。

若只想诊断传感器读数抖动，一次采集就能取得静止噪声、响应延迟和波形片段。

```powershell
$s = looptrial run sim://sensor capture | ConvertFrom-Json
looptrial wave $s.id --start 145 --count 12
Invoke-Item "$env:LOOPTRIAL_HOME\runs\$($s.id)\plot.svg"
```

每个 `runs/<id>/` 包含 `record.json`、`samples.csv` 和有单位的 `plot.svg`（有足够采样点时生成）。把整个目录复制到另一台装有相同版本的电脑，执行 `looptrial review <复制后的目录>`。复核会校验 CSV 的 SHA-256 并从采样重算指标及判据。设备、原目录和 SQLite 索引均可离线。

## 接入自己的 Agent

向支持 stdio MCP 的客户端注册 `looptrial-mcp`，或允许 Agent 在环境中执行 `looptrial`。用 `(Get-Command looptrial-mcp).Source` 获取 Windows 可执行文件的绝对路径。从 GUI 启动的客户端可在配置中指定同一 `LOOPTRIAL_HOME`。运行 `looptrial resources` 可找到 MCP 配置模板、Agent 使用说明和插件源码。返回的 `installed_guide` 目录内还有离线中文指南、完整验收记录和可执行示例。用 `looptrial-client --list` 查看客户端实际发现的工具输入。

- 初次接入先用 `devices` 和 `describe` 核实对象与范围。`read` 返回当前生效参数，`apply URI name=value` 写入并独立回读，`writes URI` 可查写入及回退回执。板卡写入 RAM，复位恢复默认。模拟器在当前实验目录保留会话值，新的目录使用模型默认值。
- `run` 使用当前生效值。可多次给出 `--condition k=v`、`--goal metric:le:value` 和 `--constraint metric:ge:value`，上下界都支持。用 `--note` 记录前文授权、阈值来源、预算或候选理由。只采集时可省略目标。摘要中的 `passed` 为 true、false 或 null，依次表示达标、未达标、只测量。
- `--background --key trial-1` 会返回编号。离开后用 `status ID` 查询，`cancel ID` 请求取消，再查终态。相同请求重用 key 可取得同一编号，独立复测请用新 key 或省略。模拟专用 `--pace 4` 在采集前保留四秒可观察的等待窗口。
- `records` 查询最近试验，`compare A B` 对相同设备、版本、动作及工况的完整记录计算 B−A。故障试验保留部分采样和最后可确认状态。CLI 的 run/status 对失败或取消返回 1，输入或操作错误返回 2，完成的测量返回 0；判定是否满足实验目标请读 `passed`。MCP 返回结构化结果，操作失败有 `error.code`。

## 设备、构建与复验

| 想做的事 | 入口 |
| --- | --- |
| 只读采集、滤波、三点标定、温控、轮速、直立与旧日志适配 | [实验指南](docs/EXPERIMENTS.md) |
| 把已有 UART 工程接到 CLI/MCP，使用 Blue Pill 的 USB 或 BLE 链路 | [固件、协议和接入指南](docs/HARDWARE.md) |
| 找到“一句症状”、不同工况、候选失败后继续和自主停止的原始记录 | [实验验收索引](docs/ACCEPTANCE.md) |
| 从标签重新构建 wheel、源码包和示例固件，核对实测版本和限制 | [发布说明与构建](docs/RELEASE.md) |
| 检查产品任务和开源复用选择 | [公开任务书](docs/GOAL.md) · [复用清单](docs/REUSE.md) |

本版使用 GPL-3.0-or-later。各依赖采用各自的许可条款。详见 [LICENSE](LICENSE) 和 [第三方声明](THIRD_PARTY.md)。
