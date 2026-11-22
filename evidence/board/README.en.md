# Blue Pill bench results · 2026-11-22

[简体中文](README.md) · **English**

A Windows host connected to the same STM32F103 Blue Pill through a USB-to-UART bridge and a BD-BT26 GATT link. A timer on the MCU updated the model. Both links completed an identity handshake, a temporary gain write and readback, a baseline, a candidate, a fresh confirmation, waveform retrieval and offline metric recalculation. The tests exercised the MCU code, timestamps, wiring, USB bridge and wireless module. Motor, balancing vehicle and thermal plant performance still require trials on those devices.

## Review the runs

Each ID directory contains `record.json`, `samples.csv` and `plot.svg`. The [CLI session](session.json) preserves requests and responses in order. Commands ran outside the checkout using a package built and installed for the test. The USB port is redacted. Each run started at zero and targeted 120 count over 16 periods of 20 ms. The final error limit was ≤0.01 count.

| Transport | Baseline, gain=2 | Candidate, gain=8 | Fresh confirmation, gain=8 |
|---|---|---|---|
| USB | [14.166 count](ce87807b99764096941e4bbdd8d17e99/record.json) | [0.001 count](1771d022950e493aa6ab2fcc7e2bf68e/record.json) | [0.001 count](b269a2ceaed647d9a3a6e37df069ae12/record.json) |
| BLE | [14.166 count](ba8fd2e23b5e4dd0b8aeb1d033695275/record.json) | [0.001 count](31b8afbc06b74979a2c5c3b66f381f92/record.json) | [0.001 count](08baa4b2e89e4381ae1111e24c98f6e0/record.json) |

Board timestamps in the two independent confirmations ranged from 0.020 to 0.320 s. The deterministic model produced identical samples under identical conditions. Writing 7 over USB yielded 7 over BLE. Writing 2 over BLE yielded 2 over USB. Both handshakes reported `bluepill-step 0.1.0`. From this directory, check the BLE confirmation offline:

```sh
looptrial review ./08baa4b2e89e4381ae1111e24c98f6e0
looptrial wave ./08baa4b2e89e4381ae1111e24c98f6e0 --count 4
```

During integration a BLE write failed with an I/O error. The host restored the previous configuration and independently read back `gain=2`. Operations within each command were then changed to reuse the same connected session, and all six runs above were repeated. The [failure receipt](ble-recovery.json) preserves the error and recovery. Device aliases added later were verified in a controlled dual-endpoint regression. The original firmware had already been restored, so the six historical records retain their original format.

## Firmware, target identification and restoration

The tested `looptrial-bluepill-0.1.0.bin` was 1564 bytes, SHA-256 `9453ee71132d1b83360d5420dfd327bf034669c421ee6c2c7311faf974b84709`. It was built with GNU Tools for STM32 14.3.1+st.2. `arm-none-eabi-size` reported text=1564, data=0 and bss=768 bytes. The bench used pySerial 3.5, Bleak 3.1.0, Python 3.12.10 and STM32CubeProgrammer 2.23.0.

One ST-LINK was present. The composite USB serial device and probe had matching serial numbers. SWD identified device 0x410, Rev X, with read protection disabled. The programmer and capacity register both reported 64 KiB. Two independent full-Flash backups matched before programming. A third check confirmed the original contents. The example was programmed, verified and reset. After the experiment, the same probe and private target identifier were used to select the board, restore the original firmware, verify and reset it. A final read of 65,536 bytes at 14:14 local time matched the backup SHA-256. Original firmware and unique hardware identifiers remain private on the workstation.

To reproduce the bench test, follow the [wiring, backup, programming and trial instructions](../../docs/HARDWARE.en.md).
