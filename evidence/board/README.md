# Blue Pill 台架实测 · 2026-11-22

Windows 电脑通过现有 USB 转 UART 与 BD-BT26 GATT，分别连接同一块 STM32F103 Blue Pill。实验对象在板内定时更新。**两条链路均完成了身份握手、临时增益写入与回读、基线、候选、独立复测、波形取回和离线重算。** 测量覆盖 MCU 代码、时间戳、接线、USB 桥及无线模块。电机、直立车体和热惯性装置的实体响应尚待对应装置验证。

## 可复核的结果

每个 ID 目录含 `record.json`、`samples.csv` 和 `plot.svg`。[完整 CLI 请求与响应](session.json) 依时间顺序保存，命令在工程目录外从本轮构建并安装的 Python 包运行。USB 端口用占位符脱敏。每次运行起点为零，目标 120 count，采 16 个 20 ms 周期，门槛为末点误差 ≤0.01 count。

| 传输 | 基线，gain=2 | 候选，gain=8 | 新试验复测，gain=8 |
|---|---|---|---|
| USB | [14.166 count](ce87807b99764096941e4bbdd8d17e99/record.json) | [0.001 count](1771d022950e493aa6ab2fcc7e2bf68e/record.json) | [0.001 count](b269a2ceaed647d9a3a6e37df069ae12/record.json) |
| BLE | [14.166 count](ba8fd2e23b5e4dd0b8aeb1d033695275/record.json) | [0.001 count](31b8afbc06b74979a2c5c3b66f381f92/record.json) | [0.001 count](08baa4b2e89e4381ae1111e24c98f6e0/record.json) |

两次独立采集的板端相对时间从 0.020 到 0.320 s。相同条件下的软件模型确定性地产生相同的样本。另经 USB 写 7，BLE 读到 7，再经 BLE 写 2，USB 读到 2。两端握手的型号与版本均为 `bluepill-step 0.1.0`。在这个文件夹运行以下命令可离线检查一条 BLE 复测记录。

```sh
looptrial review ./08baa4b2e89e4381ae1111e24c98f6e0
looptrial wave ./08baa4b2e89e4381ae1111e24c98f6e0 --count 4
```

联调中，一次 BLE 写入返回 I/O 错误，主机恢复先前配置并独立读得 `gain=2`。之后将单条命令内的多次操作复用同一已握手连接，并复验上表全部六次运行。回执保留了这次实际失败与恢复。之后加入的本地设备别名在受控双端点回归中验证，台架已恢复，六份历史记录保留原来的格式。[失败回执](ble-recovery.json)

## 固件、台架识别和还原

实测镜像 `looptrial-bluepill-0.1.0.bin` 为 1564 字节，SHA-256 为 `9453ee71132d1b83360d5420dfd327bf034669c421ee6c2c7311faf974b84709`。构建使用 GNU Tools for STM32 14.3.1+st.2，`arm-none-eabi-size` 为 text=1564、data=0、bss=768 字节。测量时使用 pySerial 3.5、Bleak 3.1.0、Python 3.12.10 和 STM32CubeProgrammer 2.23.0。

ST-LINK 唯一，USB 转串口的复合设备序号与探针一致。SWD 设备 ID 为 0x410，Rev X，读保护关闭；工具报告和容量寄存器都给出 64 KiB。原 Flash 在刷写前有两次独立的全片备份，哈希一致；动手前第三次核对同一原程序。刷入示例后执行验证及复位。实验结束，按原探针和私有目标标记选回同一块板，写回原镜像、验证并复位，于当地时间 14:14 再次读取 65,536 字节，SHA-256 与原备份一致。探针、目标的唯一标识以及原固件保留在工作站私有目录。

复验台架请使用[接线、备份、刷写及实验步骤](../../docs/HARDWARE.md)。
