# LoopTrial CLI 与 MCP 命令参考

**简体中文** · [English](CLI.md)

CLI 输出 JSON。MCP 工具使用同一组设备适配器和实验记录。运行 `looptrial --help` 查看命令帮助，`looptrial-client --list` 查看 MCP 工具的参数定义，`looptrial resources` 定位随包指南、示例适配器及 MCP 配置模板。

| 操作 | CLI | MCP 工具 |
| --- | --- | --- |
| 列出模拟器、候选串口和 BLE 预设 | `devices` | `devices` |
| 查看设备身份、信号、单位、范围和动作 | `describe URI` | `describe` |
| 读取生效参数 | `read URI` | `read_parameters` |
| 临时写入并回读 | `apply URI name=value` | `apply_parameters` |
| 查看写入和恢复回执 | `writes URI` | `parameter_history` |
| 采集一段波形 | `run URI ACTION` | `run_experiment` |
| 查找记录、查询状态或请求取消 | `records`、`status ID`、`cancel ID` | `list_runs`、`get_run`、`cancel_run` |
| 读取部分原始波形 | `wave ID --start 0 --count 8` | `waveform` |
| 校验记录并重新计算指标 | `review ID` 或 `review PATH` | `review` |
| 比较工况匹配的两次实验 | `compare FIRST SECOND` | `compare` |

### 工况与判定

下面的热阶跃实验设定 50 °C 的目标温度、升温时间目标和超调上限。参数范围和指标定义见 `describe`。

```powershell
looptrial run sim://thermal step --condition target_c=50 --goal rise_s:le:45 --constraint overshoot_c:le:1
```

需要多个工况、目标或约束时，分别重复 `--condition`、`--goal` 和 `--constraint`。比较运算支持 `le`（≤）和 `ge`（≥）。用 `--note` 记录候选参数或阈值的依据。一次采集正常完成也可能没达到指标。`passed` 为 true 或 false 表示是否达标，未设判据时为 null。CLI 的 `run` 和 `status` 对失败或取消的运行返回退出码 1，正常完成的测量返回 0。命令解析或提交前的参数错误返回 2。已分配编号的实验如果被设备能力检查拒绝，返回 1 并保留失败记录。MCP 操作错误包含 `error.code`。

### 后台运行与重试

```powershell
$job = looptrial run sim://thermal step --background --pace 4 --key demo-step | ConvertFrom-Json
looptrial status $job.id
```

模拟器的 `--pace 4` 会在采集前等待四秒实际时间。轮询 `status` 获取终态，发出 `cancel` 后也要继续查询确认。同样的请求用原 key 重试会返回已有实验编号；独立复测时省略 key 或换用新 key。

Blue Pill 的参数在 RAM 中生效直至复位。模拟器将生效设置保存在当前 `LOOPTRIAL_HOME` 中，换用新的数据目录可从默认值开始。断线后查看实验记录中的 `device_state` 和写入回执，确定最后一次确认的生效值。

### 第一次使用 MCP

在启动工作台的环境中运行 `looptrial mcp-config`，把输出的 `mcpServers.looptrial` 条目加入图形客户端的 stdio 配置。它包含本次安装的 Python 完整路径和当前实验目录。以下为手填格式示例，路径需替换为实际值。

```json
{
  "mcpServers": {
    "looptrial": {
      "command": "C:/LoopTrial/.venv/Scripts/python.exe",
      "args": ["-m", "looptrial.server"],
      "env": {"LOOPTRIAL_HOME": "C:/LoopTrial/lab"}
    }
  }
}
```

运行 `looptrial-client` 会启动本地服务、发现工具、做一次温控实验并取回结果。要单独调用工具，可建立内容为 `{"uri":"sim://thermal"}` 的 UTF-8 JSON 文件 `device.json`，再运行 `looptrial-client --tool describe --arguments device.json`。

## 与已打开的工作台共用设备

在一个终端执行 `looptrial studio`，浏览器会打开本机工作台。服务器只监听环回地址。使用 `--no-browser` 可自行打开输出的 URL，`--port` 可指定本地端口。另一个终端、Agent 或独立 MCP 客户端只要使用同一绝对路径 `LOOPTRIAL_HOME`，原有读、写、采集与取消命令就会交给该进程。CLI 或 MCP 独立运行时也能访问设备。

| 操作 | CLI | MCP |
| --- | --- | --- |
| 在工作台选择或切换设备 | `looptrial connect sim://sensor` | `session_connect` |
| 查看连接、最近样本和最后确认值 | `looptrial live` | `session_status` 返回紧凑摘要 |
| 查看谁在什么时间发出命令、收到应答和独立回读 | `looptrial timeline URI` | `session_timeline` |
| 查询参数回执和写入到独立确认的时间（毫秒） | `looptrial writes URI` | `parameter_history` |
| 实验完成或取消后关闭连接 | `looptrial disconnect` | `session_disconnect` |

持续观察时可以随时改参数。一个有界实验占用设备直至采集结束，中途冲突会返回 `device_busy`。用 `compare` 比较同工况完整试验，可以看到改变的参数以及两轮开始前最后一次写入的发起方；多项同时改变时，差值并不能归因于其中一项。独立复测应另起实验编号。轨迹无效的圈不能参与完赛用时比较。对于达标、恢复等时间，只有两轮都观测到事件时才在 `delta` 中给出精确差值。否则 `unavailable_delta[指标名]` 给出事件及 `first_observed`、`second_observed` 两个标志，其余指标仍可比较。

`sent` 表示主机已将写入提交给适配器，`applied` 表示适配器返回了生效值，`verified` 表示独立读取匹配。每批样本带主机收取时间，原始波形横轴使用设备或模型的采样时间。断线时保留最后确认值及其时间，新状态显示未知；重新连接会重新握手、核对身份并读回。工作台运行在受信本地实验环境，主机进程与板端限幅一起界定可执行操作。

四个内置测量和控制模拟器按默认工况连续预览，写入参数后从下一采样点生效。每次有界实验会从初态重新开始，采用记录中指定的工况；比较页可以叠加这些实验波形。雷霆之车的实时轨迹直接来自本轮裁判使用的采样。Blue Pill 的持续遥测与有界瞬态分别使用各自的采集时序和缓冲区。
