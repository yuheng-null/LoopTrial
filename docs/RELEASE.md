# LoopTrial 0.2.2

**简体中文** · [English](RELEASE.en.md)

从 [v0.2.2 发布页](https://github.com/yuheng-null/LoopTrial/releases/tag/v0.2.2) 下载。标签固定用于构建的源码。SHA256SUMS.txt 列出主机 wheel、完整源码分发包、板端 BIN、ELF 和实验资料包的 SHA-256。release-audit.json 记录构建提交、平台、包外安装、标准 MCP 调用与离线核验结果。

## 0.2.2 工作台

在窄屏上，连接和参数收进设备面板，波形优先显示，底栏可直接开始或停止实验。通道显示当前画面的读数，图上标明冻结或状态未知。参数草稿可撤销，切换语言可保留已输入的参数和实验工况。时间轴可筛选操作员、CLI 和 MCP。

工作台会合并同一会话连续取得的采样批次，按设备时间保留最近 60 秒内实际收到的样本。刷新页面、建立新会话后重新积累。横轴标注实际时间范围，设备序号中断处断线显示。

板端遥测提示增益变化时，主机会独立读寄存器。串口等待回复时保留单一读取者，旧版固件的空闲回读会与前台命令协调。已确认取消的设备超时报告为 `trial_timeout` 并保留可取回的样本。实验结束时若生效参数变化，记录原始采样和末次回读，只有配置一致才发布指标判定。离线复核也会检查目标和约束的运算符。

运行 `looptrial mcp-config` 可生成与当前工作台共用实验目录的 stdio 配置。压力模型 1.1 按已标定输入计算阶跃幅度，并在采样前预运行滤波器；模型 1.0 的实验仍按原判据复核。

## 0.2.1 主机修订

旧版 LT1 0.1.0 固件可在工作台上读写参数并做定长采集。空闲时主机约每秒回读一次参数，读失败后显示状态未知。持续遥测需要 0.2.0 固件。后台 MCP 试验保留发起客户端身份。新记录按设备实例关联 USB 和 BLE 写入回执，只有固件版本和本轮实际读回值都匹配才标注写入者。升级前的回执仍可查询，历史实验原件保持原貌。

本修订重建并核对了原 0.2.0 固件。旧固件兼容性在主机协议台架上复测，USB/BLE 实物性能取自 0.2.0 的同一固件。更新本机虚拟环境可再运行首页的 wheel 安装命令，沿用原实验目录。

## 发布物和入口

| 文件 | 用途 |
| --- | --- |
| looptrial-0.2.2-py3-none-any.whl | Python 3.11+ 主机包。按 README 安装后有四个入口：looptrial、looptrial-studio、looptrial-mcp、looptrial-client。Windows 实测用 CPython 3.12。首次安装需要获取依赖。 |
| looptrial-0.2.2.tar.gz | 对应主机程序、固件源码、实验示例、测试、依赖清单及许可证，可用于重建。 |
| looptrial-bluepill-0.2.0.bin、looptrial-bluepill-0.2.0.elf | STM32F103C8T6、Cortex-M3，64 KiB Flash 的双 UART 示例。BIN 的起始地址为 0x08000000。 |
| looptrial-evidence-0.2.2.zip | 公开的对话与调用、原始 CSV、记录摘要、曲线和板卡测试说明。保留相邻 CSV 与 record.json，按编号复核。 |

## 从源码重建

以下在 Windows PowerShell 执行。安装 Python 3.12。编译 Blue Pill 需要 GNU Arm Embedded GCC（验收版 14.3.1）；在 PATH 中提供 arm-none-eabi-gcc，或给固件构建脚本传入 `--toolchain-bin <bin目录>`。运行两种传输的故障回归还需要 PATH 中的本机 C 编译器 gcc 或 cc，用于把同一份 C 协议代码编译成主机动态库。

```powershell
git clone --branch v0.2.2 --depth 1 https://github.com/yuheng-null/LoopTrial.git
cd LoopTrial
git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements/build.txt
.\.venv\Scripts\python -m pip install -c requirements/windows-py312.txt .
.\.venv\Scripts\python -m pytest -q -rs
$env:SOURCE_DATE_EPOCH = "1704067200"
.\.venv\Scripts\python -m build --no-isolation --outdir dist
.\.venv\Scripts\python firmware/build.py --output dist
Get-FileHash dist\*
```

Windows 的 CPython 3.12 运行依赖快照在 requirements/windows-py312.txt；其他平台由 pyproject.toml 声明的依赖解析。SOURCE_DATE_EPOCH 固定 wheel 打包时间。发布清单的哈希用于检验下载到的实际文件。工具链、解压格式或打包程序变化后应另行核对。包外安装、MCP、离线复核命令见 [README](../README.md)。

## 验证范围

- **主机仿真**包含传感器、压力标定、热过程、轮速和小角度直立。温控可从相同初态重跑。传感器可以重放相同种子或更换噪声种子复测。仿真时间和实际耗时分别计量。示例中的阈值只适用于给定工况。
- **旧记录回放**使用可独立安装的压力记录器插件。原始计数、采样率、单位映射和峰峰值均可检查。使用自己的 CSV 时应提供实际尺度和参考标准。
- **Blue Pill** 在板内运行一阶离散软件对象，USB 串口与 BD-BT26 GATT 共用一个固件身份、RAM 参数和采样缓存。板端缓冲上限 64 点。实物连接、恢复及复验步骤在 [硬件指南](HARDWARE.md) 中。
- **实物性能**方面，本次台架仅有开发板和通信模块。外部电机、温控装置、压力传感器和两轮车均待实体试验。将工具接入实际执行器前，项目固件负责具体动作许可、物理限值、独立超时与回退。
- **并发与状态**方面，同一 LOOPTRIAL_HOME 由本机锁和目录索引协调。两个客户端访问一块板时应共用这个目录。串口或 BLE 参数变更只写 RAM。中断后的状态、超出预算的搜索及缺少独立参考的标定，依记录中最后一次有效读数解释。跨上电保存需要设备另行实现持久化动作。
- **平台**方面，本版实际发布验收在 Windows x64、Python 3.12 上执行。其他 Python / OS 组合和型号可按对应后端运行回归后确认。

原创建模、工具代码和示例固件采用 GPL-3.0-or-later。各依赖及复用说明见 [第三方声明](../THIRD_PARTY.md)。

## 工作台与整车

`looptrial studio` 提供本机工作台和共享连接。界面与 CLI/MCP 共用同一个数据目录。随 wheel 提供浏览器页面、Three.js r128、固定提交的雷霆之车算法和自绘赛道，整车试跑需本机已安装支持 WebGL 的 Edge 或 Chromium。使用 `LOOPTRIAL_BROWSER` 可指定可执行文件。首次安装下载依赖后，模拟器、波形、复核均可在本机完成。验收与证据见[本版报告](ACCEPTANCE-0.2.md)和[物理链路记录](../evidence/v02/board/README.md)。
