# Blue Pill 共享台架 · v0.2.0

**简体中文** · [English](README.en.md)

2026-11-23，Windows PC 分别通过 USB 转串口（PA2/PA3）和 BD-BT26 的 BLE GATT（USART1 重映射到 PB6/PB7），访问同一块 STM32F103C8T6。两路 MCU UART 均为 9600 8N1。被改变的对象是板内按时钟运行的一阶软件模型。传感器、实体车辆、外部电机和水池性能需由相应装置验证。

## 同一个蓝牙会话中的人工操作和 Agent

Edge 实际打开工作台，浏览器自动化在页面中连接 BD-BT26，并用参数框填入 3。保持该页面打开和实时绘图，同时从另一个进程启动已登录的 Codex CLI，经标准 stdio MCP 连接相同的工作台数据目录。用户要求保持 120 count、16 点和 20 ms 的工况并把末点误差调到 0.01 count 以内。Agent 自己读取基线、选择增益、新开试验复测、读回，并通过第二轮对话核对随后的人为更改。[用户原话、Agent 回复和实际 MCP 报文](shared/agent.jsonl) · [实际界面截图](shared/waveform.png) · [浏览器显示记录](shared/rendered.json)

| 谁发起 | 实验 | 实际 gain | 末点误差（count） |
|---|---|---:|---:|
| 页面设为 3，MCP 采基线 | [32cfec0a](shared/runs/32cfec0a53584e39bdb2ba6a2e578619/record.json) | 3 | 4.326 |
| MCP 写入，W 应答并独立 R 回读，采候选 | [92f6926a](shared/runs/92f6926a555b48c7a8e8c712645bcd0d/record.json) | 8 | 0.001 |
| MCP 新试验确认 | [edecbc9d](shared/runs/edecbc9d7e95426787768fcd26a3ba5c/record.json) | 8 | 0.001 |
| 页面改为 6，MCP 发现改变并同工况重采 | [74d4faaf](shared/runs/74d4faafea82437980b94ad7a6becdbe/record.json) | 6 | 0.064 |

第四次实验仍可和第三次比较参数效果；它无法作为 gain=8 的重复确认。Agent 在回复中识别了更改时间、发起者、实际增益、两轮工况和超限误差。USB 的对应实验为 [gain=2 基线](shared/runs/75d624d2f9fd45ff9545e999ec668785/record.json)、[gain=8 候选](shared/runs/a71ced468d8b4d9f9516ed8b7e9c7180/record.json)和[独立复测](shared/runs/168d9a7ea301433d989c9637d1056ea2/record.json)，误差分别为 14.166、0.001、0.001 count。

## 持续采样和链路带宽

**底层持续连接。** 观察线程按目标 120 ms 的主机请求间隔并发轮询，一个请求最多取四条 50 ms 板端采样。前台依次写入增益、独立回读、采集基线及候选、复测和取消。在观测区间首尾，计算设备序号变化除以设备时差、非空批次间隔的平均速率以及未连续的序号数。每条写入的确认延迟从开始发送 W 到读到 R 结果，包含串行化排队。下列 45 秒窗口并非链路的标称极限。

| 链路 | 板端帧率 | 主机非空批次/s | 收到的帧 / 漏帧 | 最长批次间隔 | 8 次写入至回读的中位数 / 最大值 |
|---|---:|---:|---:|---:|---:|
| USB | 20 Hz | 6.92 | 900 / 0 | 0.634 s | 110 / 451 ms |
| BLE | 20 Hz | 5.87 | 867 / 30 | 0.376 s | 450 / 488 ms |

[USB 逐帧时标](usb/telemetry.csv) · [USB 写入与阶跃原始样本](usb/session.json) · [BLE 逐帧时标](ble/telemetry.csv) · [BLE 写入与阶跃原始样本](ble/session.json)

**打开工作台的实测。** 同一块板上，Edge 打开实时页面，共享服务依次处理七次 CLI 写入及回读、三次相同工况的阶跃实验。在每套调度下观察约 45 秒，以下为会话从连接到截取统计时的总计。

| 工作台会话 | 板端采样率 | 主机非空更新/s | 收到 / 缺失的样本数 |
|---|---:|---:|---:|
| BLE，每次通信后再等 100 ms（初测） | 20 Hz | 3.86 | 716 / 206 |
| BLE，读满一页立即续取（发布版） | 20 Hz | 5.99 | 906 / 31 |
| USB，相同发布版策略 | 20 Hz | 9.01 | 918 / 0 |

在 BLE 上，固定休眠会随 GATT 事务耗时一同累加。发布版根据请求的开始时间安排下次轮询，读满一页时立即续取。并发时仍可能超过 1.6 秒环形缓存的保留时间；上位机按设备帧号报告缺样，正式实验另取板端定长缓存。本文前面的 Agent 对话和首次截图采于优化前。三次会话均保留统计、写入延迟、实验编号和指标。[初测](shared/ble-before.json) · [发布版 BLE](shared/ble-adaptive.json) · [发布版 USB](shared/usb-adaptive.json) · [更新后的实物界面](shared/workbench-release.png)

## 中断、取消和恢复

- **BLE 真断链。** 在 64 × 100 ms 实验中，将 Windows 蓝牙无线电切为 OFF，终止实际 GATT 连接。运行失败，工作台标为未知，保留最近已确认的 gain=6 和时间。重新开启无线电、握手与独立读取，读回 6。实验没有重新启动。[断线、重新连接、状态和时间轴](shared/ble-interruption.json)
- **USB 下位机复位。** 实验进行中通过已核对的 ST-LINK 复位 MCU；物理串口桥仍接在电脑上。板端原实验 token 遗失，Q 返回 `unknown_trial`，记录保留最近确认 gain=8。重新握手读得上电默认 2。USB 插头始终就位，本项复现的是串口仍在但目标状态丢失。[失效实验和独立回读](shared/usb-interruption.json)
- **用户取消。** 两路独立持续连接都执行了设备端 X 指令，设备确认停止，取回停止前的采样，随后读回 gain=8。前台限长实验的高速缓存与在线预览分别记数。[USB 回执](usb/session.json) · [BLE 回执](ble/session.json)

## 复验

按[接线、完整备份、刷写与恢复指南](../../../docs/HARDWARE.md)准备台架。启动 `looptrial studio`，在页面连接实际 USB 串口或 `ble://BD-BT26`，保持页面打开。在使用同一 `LOOPTRIAL_HOME` 的另一终端运行如下命令。

```powershell
$link = 'ble://BD-BT26'
looptrial live
looptrial apply $link gain=8
looptrial run $link step --condition target=120 --condition samples=16 --condition period_ms=20 --goal final_error:le:0.01
looptrial timeline $link
```

安装包外的复核只需运行 `looptrial review ./shared/runs/edecbc9d7e95426787768fcd26a3ba5c`（在本目录执行）。各编号目录含记录和原始 CSV。完成的试验附有曲线，两份中断记录含失败原因及可用行数。

## 烧录与还原

当天只枚举到一支 ST-LINK，USB 串口桥的复合设备父标识与探针一致。SWD 器件 ID 为 0x410，RDP 已关闭，容量寄存器为 0x0040，编程器报告为 64 KiB。烧录前两次读取全部用户 Flash，SHA-256 一致；再次核对探针和板端 UID，第三次全读仍与备份相符，再下载、校验和复位。实测的 v0.2.0 BIN 共 2036 字节，SHA-256 为 `d0fc65484ba3c38729f8bc1645a227a8de3e64a533268cd29bccbf02f88a6127`。测试结束后，按同一探针与 UID 重选目标，写回原镜像、校验并复位。当地时间 15:31 又读回全部 65536 字节，哈希与原始备份相同。Windows 蓝牙在测试开始前为关闭状态，测试后已恢复关闭。探针序号、芯片 UID、原镜像和私有校验信息留在工作站。
