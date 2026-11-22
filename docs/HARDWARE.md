# Blue Pill 实验与既有固件接入

**简体中文** · [English](HARDWARE.en.md)

示例面向 STM32F103C8T6，使用 64 KiB Flash、20 KiB SRAM 的链接布局。板内运行一阶软件对象。每次阶跃将输出置零，按设定周期更新并缓存测量值，串口和 GATT 均可读取同一对象。通电默认 `gain=2`，范围 1～16，修改保存在 RAM。本例占用两组 USART 和 SysTick，复位时钟为 HSI 8 MHz。

| 接口 | Blue Pill | 接线或用途 |
|---|---|---|
| ST-LINK | PA13/SWDIO、PA14/SWCLK、GND、目标电压参考 | 按探针说明连接和供电，保留 SWD |
| USB 转串口 | PA2/USART2_TX、PA3/USART2_RX | 3.3 V 逻辑，TX 接对端 RX、RX 接对端 TX、共地，9600 8N1 |
| BD-BT26 | PB6/USART1_TX、PB7/USART1_RX | USART1 重映射，两板收发交叉、共地，模块 UART 9600 8N1 |

### 构建、备份与恢复

安装 Python 3.11+、GNU Arm Embedded 工具链。Windows 实测 ST GNU Tools for STM32 14.3.1+st.2。脚本查找 PATH 和 Windows 用户目录中的 ST bundle，其他布局可传 `--toolchain-bin <bin目录>`。在发布源码根目录运行以下命令，或直接从发布页取得已构建的 BIN。

```sh
python firmware/build.py --output dist/firmware
```

`looptrial-bluepill-0.1.0.bin` 从 `0x08000000` 写入。`looptrial-bluepill-0.1.0.elf` 保留符号。固件源码独立于 HAL、RTOS 和 C 运行库。复建同版本字节请采用发布说明所列编译器及源码提交。

在 **PowerShell** 中将 `STM32_Programmer_CLI` 所在目录加入 PATH，在私人工作目录操作。下面的命令针对已经核对为 **64 KiB** 的单块目标。先列出探针，将所选探针序号填入变量。检查选项字节 RDP 为 Disabled，核对紧接的器件 ID、容量、Flash 容量寄存器（本型号 64 KiB 读出 `0040`）和接线。无法确认目标、完整读取或备份不一致时，结束这次烧录。

```powershell
STM32_Programmer_CLI -l st-link
$probe = '<所选探针的序号>'
$connect = @('-c', 'port=SWD', "sn=$probe")
STM32_Programmer_CLI @connect mode=HOTPLUG -ob displ -r16 0x1FFFF7E0 2
```

确认 `original.bin`、`original-check.bin` 和 `restored.bin` 为新的私有文件名。以下备份检查应在刷写前单独完成。所有编程命令遇到报错都应停下检查目标状态。

```powershell
if ((Test-Path original.bin) -or (Test-Path original-check.bin)) { throw 'Choose a new backup directory.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 original.bin
if ($LASTEXITCODE) { throw 'Backup read failed.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 original-check.bin
if ($LASTEXITCODE) { throw 'Second read failed.' }
$originalHash = (Get-FileHash original.bin).Hash
if ((Get-Item original.bin).Length -ne 65536 -or (Get-FileHash original-check.bin).Hash -ne $originalHash) { throw 'Backup verification failed.' }
```

在 BIN 所在路径和台架与备份时一致的条件下刷入示例，执行实验后恢复原镜像并再次整片读取。备份覆盖用户 Flash，保存在本地。这些步骤不更改选项字节。

```powershell
# 按成品的实际位置调整路径
STM32_Programmer_CLI @connect -d ./looptrial-bluepill-0.1.0.bin 0x08000000 -v -rst
if ($LASTEXITCODE) { throw 'Example flash verification failed.' }
```

先完成下节的连通和实验。结束测试、核对目标仍是原板后，再单独执行恢复。

```powershell
STM32_Programmer_CLI @connect -d original.bin 0x08000000 -v -rst
if ($LASTEXITCODE) { throw 'Restore failed.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 restored.bin
if ($LASTEXITCODE -or (Get-FileHash restored.bin).Hash -ne $originalHash) { throw 'Full flash restore mismatch.' }
```

### 连通、回读与复测

先安装发布包。用 `looptrial devices` 查 USB 串口，以下将 `COM8` 换为本机实际端口。Linux 的端口示例为 `serial:///dev/ttyUSB0`。将同一组命令的 `$link` 改为 `'ble://BD-BT26'` 可走 GATT。BLE 客户端按广播名或本机地址发现外设，必须匹配唯一设备。相同名字存在多台时用地址，公开记录中保留传输类型。每次连接均校验 LT1、板端型号和版本。

```powershell
looptrial devices
$link = 'serial://COM8'
looptrial describe $link
looptrial read $link
looptrial apply $link gain=2
looptrial run $link step --condition target=120 --condition samples=16 --condition period_ms=20 --goal final_error:le:0.01
looptrial apply $link gain=8
looptrial run $link step --condition target=120 --condition samples=16 --condition period_ms=20 --goal final_error:le:0.01
looptrial run $link step --condition target=120 --condition samples=16 --condition period_ms=20 --goal final_error:le:0.01
looptrial read 'ble://BD-BT26'
looptrial apply $link gain=2
```

输出中的 `id` 对应本次实验。用 `looptrial review <id>` 从 CSV 重新算指标。BLE 默认服务 FFE0，订阅 FFE1，在 FFE1、FFE2 中选择支持写的特征。可显式指定 `'ble://BD-BT26?service=ffe0&notify=ffe1&write=ffe2'`。模块断开后会有重新广播的间隔，Windows 一次命令可能包含数次扫描及握手。USB 串口路径在此例中由 USB 转 UART 桥接，经典蓝牙虚拟串口无法提供该 GATT 路径。

### 板端时间、数据与线协议

响应计算在 SysTick 的 1 ms 节拍中完成，主循环发送数据。每个采样周期把 `gain/16` 倍的剩余误差加到当前值，以 0.001 count 向上取整。第一个样本在一个周期后产生。固定操作范围为 4～64 个样本，10～100 ms 周期及 1～1000 count 目标，最长 6.4 s 自行结束。没有对外执行器输出。样本行的 `t` 是板上相对起点的秒数，取数时间和蓝牙延迟不会改变波形。

LT1 使用以 LF 结束的 ASCII 帧，两条链路各有一个独立的字节流解析器。请求为 `@<seq> <op> [无符号十进制参数...]\n`。成功返回 `@<seq> OK [字段...]\n`，失败返回 `@<seq> ERR <code>\n`。一个通信方一次只有一个待答请求。`seq` 关联应答，采集使用独立的非零随机 32 位 `token`。响应字段如下。

| 操作 | 请求参数 | OK 后的字段 |
|---|---|---|
| H | 无 | LT1、型号、固件版本、仅在连接时比较的单元标记 |
| R | 无 | 当前 gain |
| W | gain | 写后 gain，再用 R 独立读取 |
| S | token target period_ms samples expected_gain | 无，板端原子核对期望增益并启动 |
| Q | token | 状态、已缓存样本数、启动时 gain |
| F | token offset | offset、返回行数、若干组相对毫秒与千分之一 count 的响应值 |
| X | token | 停止后的状态、样本数、启动时 gain |

状态值为 1 运行、2 完成、3 已取消。采集中 W 和另一项新 S 返回 `busy`。同 token 同配置重发 S 取回之前的受理结果，冲突配置返回 `conflict`。所存当前批次及最近八个已替代 token 的去重历史在复位时清空；设备只保留最近一项实验的采样缓冲。主机按实验编号长期保存数据，CLI 的 `--key` 独立提供跨进程的持久幂等请求。传输中断时主机重新握手，比较单元标记并只按原 token 查询、续取。复位或换板导致无法续取会产生失败记录。可取消实验并取回已采前缀。该小协议面向可信试验台，串口文本帧本身没有鉴权或应用层 CRC。

主机对每项实验只发送一次 S。启动应答丢失时，主机用 Q 查询原 token；若 MCU 已复位，桥仍连通，Q 也可能返回 `unknown_trial`。这种情况下记录为失败且设备状态未知。复核人仍能区分查询到原试验和失去试验状态两种结局。

### 接入手里的工程

1. 从工程的采样回调、变量定义和控制任务确认单位、符号、时钟来源与采样周期。找到实际生效的配置和应用时刻。先暴露一个只读量，用已知静止值或已知阶跃核对原始输出和时间戳。传感器标定需要独立已知参考，回放只能复算已有记录。
2. 对支持这个板内示例协议的端点，移植 `firmware/looptrial.c`、`looptrial.h` 两个文件。在主循环或通信任务把各端口收到的字节分别交给 `lt_receive(&decoder, byte, send, port)`。每个连接分配并清零自己的 `lt_decoder`，`send` 输出一个字节。启动一次 `lt_init(tag)`，调用端提供稳定的本地标记。`lt_tick()` 来自 1 ms 的周期上下文。不要把阻塞发送放在高优先级控制 ISR 内。
3. 新装置保留其已有实时环和协议时，在采样点写入预分配的环形或定长缓冲。激励在板端启动，按装置允许的限幅、超时、取消及空闲状态结束；参数先校验、在确定的循环边界提交，再读生效变量。按批次提供带时间和索引的缓存页。真实执行器需要实现其装置特定的限幅和回退。
4. 在 Python 包注册 `looptrial.devices` 入口点，返回该固件的真实身份及版本，在 `describe` 中列出信号单位、允许的参数与动作范围。只读设备使用空的 `parameters`。把后端的 `read/apply/acquire` 映射到现有协议，`metrics` 仅依赖保存的参数条件和样本行，以便脱机复核。`looptrial resources` 给出已安装的示例路径，可从其中的 `pressure_adapter` 开始。命令和 MCP 操作会复用该描述。LT1 自带主机描述按型号和版本匹配，新固件需要自己的描述及校验。

记录中的板卡 `instance` 来自本地私有盐和握手标记。同一数据目录内，USB 和 BLE 连接同一板会得到相同别名，换数据目录会得到独立的别名。示例使用 32 位单元标记，存在碰撞可能，批量生产设备可在自定义握手中提供更长标记。[实物验收与记录](../evidence/board/README.md)

引脚映射依据 ST RM0008 Rev 21 表 54（第 181 页）。[ST 参考手册](https://www.st.com/resource/en/reference_manual/rm0008-stm32f101xx-stm32f102xx-stm32f103xx-stm32f105xx-and-stm32f107xx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf) · [模块资料](https://botelvdong.com/courses/Modules/docs/bluetooth/Summary) · [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html) · [BleakClient API](https://bleak.readthedocs.io/en/stable/api/client.html)
