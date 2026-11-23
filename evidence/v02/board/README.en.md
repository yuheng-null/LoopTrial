# Shared Blue Pill bench · v0.2.0

[简体中文](README.md) · **English**

On 2026-11-23 a Windows PC used a USB-to-UART bridge on PA2/PA3 and a BD-BT26 BLE GATT link on remapped USART1 PB6/PB7 to access the same STM32F103C8T6. Both MCU UARTs used 9600 8N1. A clocked first-order software plant ran on the MCU. External motors, real race vehicles, sensor performance and pool operation still require device-specific trials.

## The operator and agent on one BLE connection

Browser automation operated a visible Edge workbench, connected the BD-BT26 and typed 3 into the gain field. A separate signed-in Codex CLI process connected over stdio MCP to the same workbench data directory while the page continued plotting. The user requested at most 0.01 count final error at a 120 count target, over 16 samples at 20 ms. The agent obtained the baseline, chose a gain, ran a candidate and a fresh confirmation and read back effective values. A follow-up exchange checked a subsequent operator change. [User messages, agent replies and actual MCP calls](shared/agent.jsonl) · [Rendered workbench](shared/waveform.png) · [Displayed status and events](shared/rendered.json)

| Actor and experiment | Run | Effective gain | Final error (count) |
|---|---|---:|---:|
| UI set 3, MCP acquired the baseline | [32cfec0a](shared/runs/32cfec0a53584e39bdb2ba6a2e578619/record.json) | 3 | 4.326 |
| MCP wrote gain, received W acknowledgement and independent R, then acquired | [92f6926a](shared/runs/92f6926a555b48c7a8e8c712645bcd0d/record.json) | 8 | 0.001 |
| MCP ran a new confirmation | [edecbc9d](shared/runs/edecbc9d7e95426787768fcd26a3ba5c/record.json) | 8 | 0.001 |
| UI changed gain to 6, MCP discovered the change and measured again | [74d4faaf](shared/runs/74d4faafea82437980b94ad7a6becdbe/record.json) | 6 | 0.064 |

The fourth trial supports a comparison of two gains under the same conditions. A repeat confirmation of gain 8 requires the original gain. The agent identified the time, actor, effective value, matching conditions and excess error. The wired [baseline](shared/runs/75d624d2f9fd45ff9545e999ec668785/record.json), [candidate](shared/runs/a71ced468d8b4d9f9516ed8b7e9c7180/record.json) and [fresh confirmation](shared/runs/168d9a7ea301433d989c9637d1056ea2/record.json) had errors of 14.166, 0.001 and 0.001 count.

## Sustained observation and bandwidth

**Persistent link benchmark.** A telemetry thread targeted a 120 ms request interval. Each reply carried up to four samples at 50 ms board intervals. Concurrent foreground operations wrote gains and read them back, captured a baseline, candidate and confirmation, and cancelled a longer trial. Board rate uses the sequence and device time spans. Host update rate uses distinct nonempty page arrival times. Missing counts use sequence discontinuities. Write latency covers the dispatch of W through the independent R reply, including contention. The 45 s windows characterize this bench.

| Link | Board rate | Host batches/s | Received / missed samples | Largest batch interval | Median / max write to readback (8 writes) |
|---|---:|---:|---:|---:|---:|
| USB | 20 Hz | 6.92 | 900 / 0 | 0.634 s | 110 / 451 ms |
| BLE | 20 Hz | 5.87 | 867 / 30 | 0.376 s | 450 / 488 ms |

[USB timestamped rows](usb/telemetry.csv) · [USB receipts and raw step captures](usb/session.json) · [BLE timestamped rows](ble/telemetry.csv) · [BLE receipts and raw step captures](ble/session.json)

**Rendered workbench measurements.** With Edge displaying the live workbench, each session processed seven CLI writes with independent readback and three identical step conditions on the same board. Each observation window was approximately 45 s. Counts are cumulative from connection to the final snapshot.

| Workbench session | Board rate | Nonempty host updates/s | Received / missed samples |
|---|---:|---:|---:|
| BLE, 100 ms idle after each transaction (initial implementation) | 20 Hz | 3.86 | 716 / 206 |
| BLE, drain full pages immediately (release scheduling) | 20 Hz | 5.99 | 906 / 31 |
| USB, same release scheduling | 20 Hz | 9.01 | 918 / 0 |

Fixed sleeps added to the duration of each GATT transaction. The release paces poll starts and requests the next page immediately when the current page is full. Contention can still exceed the ring's 1.6 s retention; sequence gaps remain visible. Bounded trials retain their own capture buffer. The agent exchange and initial screenshot above used the earlier polling schedule. All three session records include periodic statistics, per-write latency, run IDs and metrics. [Earlier BLE session](shared/ble-before.json) · [Release BLE session](shared/ble-adaptive.json) · [Release USB session](shared/usb-adaptive.json) · [Updated physical workbench](shared/workbench-release.png)

## Interruption, cancellation and recovery

- **Actual BLE link interruption.** Switching off the Windows Bluetooth radio during a 64 × 100 ms run terminated GATT. The trial failed. The workbench displayed unknown current state with the last confirmed gain of 6 and its time. Enabling the radio again, handshaking and reading the board confirmed 6. The experiment did not restart. [Link, run, timeline and reconnection](shared/ble-interruption.json)
- **MCU reset over USB.** ST-LINK reset the identified target during a trial while its USB serial bridge remained connected. The board lost the token, Q returned `unknown_trial`, and the record retained the last confirmed gain of 8. A new handshake and read returned the power-on default of 2. The physical USB plug stayed in place. [Failed run and independent readback](shared/usb-interruption.json)
- **Requested cancellation.** Both persistent links executed X, obtained the board's cancelled state and retrieved the available sample prefix. After each stop R returned gain 8. Bounded acquisition uses a separate buffer from the live preview. [USB receipt](usb/session.json) · [BLE receipt](ble/session.json)

## Repeat the bench

Follow the [wiring, full backup, flashing and restoration guide](../../../docs/HARDWARE.en.md). Start `looptrial studio`, connect to your USB serial port or `ble://BD-BT26` in the workbench and leave it open. Run the following from another shell with the same `LOOPTRIAL_HOME`.

```powershell
$link = 'ble://BD-BT26'
looptrial live
looptrial apply $link gain=8
looptrial run $link step --condition target=120 --condition samples=16 --condition period_ms=20 --goal final_error:le:0.01
looptrial timeline $link
```

From this directory, run `looptrial review ./shared/runs/edecbc9d7e95426787768fcd26a3ba5c` to recompute a result offline. Each run directory includes its record and raw CSV. Completed runs include plots. The two interruption records contain the failure reason and sample count.

## Programming and restoration

One ST-LINK was present and its identity matched the USB bridge composite parent. SWD reported device ID 0x410 and disabled read protection. The Flash capacity register read 0x0040 and the programmer reported 64 KiB. Two full user Flash reads matched by SHA-256. Before writing, probe and device UID were rechecked and a third full read matched the backup. The board image was written, verified and reset. The tested v0.2.0 BIN is 2036 bytes, SHA-256 `d0fc65484ba3c38729f8bc1645a227a8de3e64a533268cd29bccbf02f88a6127`. After all testing the same probe and target UID were checked, the original image was restored, verified and reset. A final 65536-byte read at 15:31 local time matched the original SHA-256. Windows Bluetooth was initially off and was returned to off. Original firmware, private hashes and unique hardware identifiers remain on the workstation.
