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

需要多个工况、目标或约束时，分别重复 `--condition`、`--goal` 和 `--constraint`。比较运算支持 `le`（≤）和 `ge`（≥）。用 `--note` 记录候选参数或阈值的依据。一次采集正常完成也可能没达到指标。`passed` 为 true 或 false 表示是否达标，未设判据时为 null。CLI 的 `run` 和 `status` 对失败或取消的运行返回退出码 1，正常完成的测量返回 0。参数无效或操作出错返回 2。MCP 操作错误包含 `error.code`。

### 后台运行与重试

```powershell
$job = looptrial run sim://thermal step --background --pace 4 --key demo-step | ConvertFrom-Json
looptrial status $job.id
```

模拟器的 `--pace 4` 会在采集前等待四秒实际时间。轮询 `status` 获取终态，发出 `cancel` 后也要继续查询确认。同样的请求用原 key 重试会返回已有实验编号；独立复测时省略 key 或换用新 key。

Blue Pill 的参数在 RAM 中生效直至复位。模拟器将生效设置保存在当前 `LOOPTRIAL_HOME` 中，换用新的数据目录可从默认值开始。断线后查看实验记录中的 `device_state` 和写入回执，确定最后一次确认的生效值。

### 第一次使用 MCP

将已安装的 `looptrial-mcp` 注册到客户端的 stdio 配置。下面是常见的格式。GUI 客户端的 PATH 可能与终端不同，这时填写完整可执行文件路径；指定与 CLI 相同的 `LOOPTRIAL_HOME` 绝对路径可共用记录。

```json
{
  "mcpServers": {
    "looptrial": {
      "command": "looptrial-mcp",
      "args": []
    }
  }
}
```

运行 `looptrial-client` 会启动本地服务、发现工具、做一次温控实验并取回结果。要单独调用工具，可建立内容为 `{"uri":"sim://thermal"}` 的 UTF-8 JSON 文件 `device.json`，再运行 `looptrial-client --tool describe --arguments device.json`。
