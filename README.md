# LoopTrial

**简体中文** · [English](README.en.md)

LoopTrial 是给嵌入式工程师和 AI Agent 用的实验工具。接入设备后，你可以采一段波形诊断问题，也可以让 Agent 调整参数、读回生效值，在相同工况下重做实验。每次运行都有独立编号，原始采样和计算结果可以一起交给队友。

例如，你先告诉 Agent「这台温控器平时工作在 50 °C」，之后只说「升温太慢，帮我调快一点」。Agent 可以从设备描述中找到温度、加热输出和可写增益，先跑一次基线，再比较升温时间和超调。候选合格后重新运行确认；若输出已经持续顶到上限，也可以保留原配置，把停止原因和波形交给你。

[下载 v0.1.0](https://github.com/yuheng-null/LoopTrial/releases/tag/v0.1.0) · [实验示例](docs/EXPERIMENTS.md) · [已有工程接入](docs/HARDWARE.md)

## 可以用它做什么

| 用途 | 随包示例 |
| --- | --- |
| 测量与信号处理 | 在同一段压力输入上比较滤波前后的静止噪声和响应延迟。 |
| 传感器标定 | 用两个已知参考点求零点和比例系数，留出第三点检查误差。 |
| 控制器调试 | 温控看升温时间和超调，轮速看跟踪误差和输出饱和，两轮直立看扰动后的倾角恢复和车轮漂移。 |

![模拟压力阶跃的原始读数和滤波曲线。滤波减小了静止时的噪声，也让阶跃边沿变缓。](docs/media/pressure-filter.png)

同一段模拟压力采样，滤波后读数更稳，跟上台阶也多用了约 0.2 秒。下面的命令可以重做这组比较。

## 第一次使用

安装 Python 3.12 和 Windows Python Launcher，将[主机安装包](https://github.com/yuheng-null/LoopTrial/releases/download/v0.1.0/looptrial-0.1.0-py3-none-any.whl)下载到一个空目录，然后在该目录打开 PowerShell。首次安装需要联网获取依赖，内置模拟器在本机运行。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install .\looptrial-0.1.0-py3-none-any.whl
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:LOOPTRIAL_HOME = "$PWD\lab"
```

用同一个随机种子采两次，让滤波器收到相同的原始信号。两次 `apply` 都会返回实际生效的参数。

```powershell
looptrial describe sim://sensor
looptrial apply sim://sensor alpha=1
$a = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial apply sim://sensor alpha=0.2
$b = looptrial run sim://sensor capture --condition seed=17 | ConvertFrom-Json
looptrial compare $a.id $b.id
looptrial review $b.id
```

`compare` 给出第二次减去第一次的指标差值。打开 `lab/runs/<id>/` 可以看到参数和工况（`record.json`）、带时间戳的采样（`samples.csv`）及波形（`plot.svg`）。把整个目录复制到另一台装有 LoopTrial 的电脑，即可用 `looptrial review <目录>` 离线校验并重算。

## 接入自己的 Agent 或设备

- **Agent** 可以直接执行 CLI，也可以通过 MCP（Model Context Protocol）调用同一套操作。向支持 stdio 的客户端注册 `looptrial-mcp`，可用 `(Get-Command looptrial-mcp).Source` 获得绝对路径。让客户端使用与 CLI 相同的 `LOOPTRIAL_HOME` 即可共享记录。运行 `looptrial-client` 可通过独立的标准 MCP 客户端完成一次实验。
- **实物设备**通过固件或适配器声明信号、单位、允许写入的参数和实验动作。随包的 STM32F103 Blue Pill 固件演示 USB 转串口与 BD-BT26 蓝牙 GATT 两种接法。已有通信协议也可以由小型 Python 适配器接入。实时采样与控制留在设备或本地程序，Agent 根据每轮结果决定下一步。

## 文档与许可

[CLI / MCP 命令参考](docs/CLI.md) · [跨领域实验与适配器示例](docs/EXPERIMENTS.md) · [Blue Pill 接线、协议与固件接入](docs/HARDWARE.md) · [发布与源码构建](docs/RELEASE.md) · [验收记录](docs/ACCEPTANCE.md)

LoopTrial 采用 **GPL-3.0-or-later**。依赖项目保留各自的许可证。[完整许可](LICENSE) · [第三方声明](THIRD_PARTY.md)
