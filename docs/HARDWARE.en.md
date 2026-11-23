# Blue Pill bench and existing firmware integration

[简体中文](HARDWARE.md) · **English**

Use one active physical link per lab. The operator and agent share the connection owned by the workbench. To check the other transport, finish the trial, disconnect, then switch. The example firmware polls both UARTs and can drop bytes if independent hosts transmit at the same time.

The STM32F103C8T6 example uses a 64 KiB Flash / 20 KiB SRAM linker layout. Each step resets the first-order software model's output to zero, then updates and buffers it at the requested period. Serial and GATT access the same model. The power-on default is `gain=2`, the range is 1–16, and changes are held in RAM. The example uses two USARTs, SysTick and the reset clock (8 MHz HSI).

| Interface | Blue Pill pins | Wiring and use |
|---|---|---|
| ST-LINK | PA13/SWDIO, PA14/SWCLK, GND, target voltage reference | Wire and power the target according to the probe instructions. Keep SWD available. |
| USB-to-UART | PA2/USART2_TX, PA3/USART2_RX | 3.3 V logic. Cross TX and RX, share ground, 9600 8N1. |
| BD-BT26 | PB6/USART1_TX, PB7/USART1_RX | Remapped USART1. Cross TX and RX, share ground, module UART at 9600 8N1. |

### Build, back up and restore

Install Python 3.11+ and GNU Arm Embedded tools. The Windows test used ST GNU Tools for STM32 14.3.1+st.2. The script searches PATH and the Windows user's ST bundles. For another layout, pass `--toolchain-bin <bin-directory>`. From the root of the release source, run the command below or download the prebuilt BIN from the release.

```sh
python firmware/build.py --output dist/firmware
```

Write `looptrial-bluepill-0.2.0.bin` starting at `0x08000000`. The ELF retains symbols. The firmware runs independently of HAL, an RTOS and the C runtime. To reproduce release bytes, use the compiler and source commit in the [release guide](RELEASE.en.md).

In **PowerShell**, add the directory containing `STM32_Programmer_CLI` to PATH and use a private working directory. These commands assume **one positively identified 64 KiB target**. List probes and put the selected serial number in the variable. Check that the RDP option byte is Disabled. Check the device ID, reported capacity, Flash capacity register (`0040` for this 64 KiB part) and physical wiring. Stop if the identity, full read or matching backups cannot be confirmed.

```powershell
STM32_Programmer_CLI -l st-link
$probe = '<selected probe serial number>'
$connect = @('-c', 'port=SWD', "sn=$probe")
STM32_Programmer_CLI @connect mode=HOTPLUG -ob displ -r16 0x1FFFF7E0 2
```

Choose unused private filenames for `original.bin`, `original-check.bin` and `restored.bin`. Complete the backup checks separately before programming. Stop and inspect the target if a programmer command fails.

```powershell
if ((Test-Path original.bin) -or (Test-Path original-check.bin)) { throw 'Choose a new backup directory.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 original.bin
if ($LASTEXITCODE) { throw 'Backup read failed.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 original-check.bin
if ($LASTEXITCODE) { throw 'Second read failed.' }
$originalHash = (Get-FileHash original.bin).Hash
if ((Get-Item original.bin).Length -ne 65536 -or (Get-FileHash original-check.bin).Hash -ne $originalHash) { throw 'Backup verification failed.' }
```

With the same bench and target still connected, run the next command from the directory containing the BIN. The backup covers user Flash and stays private. These operations preserve option bytes.

```powershell
# Adjust the path to the downloaded or built firmware.
STM32_Programmer_CLI @connect -d ./looptrial-bluepill-0.2.0.bin 0x08000000 -v -rst
if ($LASTEXITCODE) { throw 'Example flash verification failed.' }
```

Perform the connection and trial steps below. After testing, identify the original board again, then run the restoration and full readback separately.

```powershell
STM32_Programmer_CLI @connect -d original.bin 0x08000000 -v -rst
if ($LASTEXITCODE) { throw 'Restore failed.' }
STM32_Programmer_CLI @connect mode=HOTPLUG -u 0x08000000 65536 restored.bin
if ($LASTEXITCODE -or (Get-FileHash restored.bin).Hash -ne $originalHash) { throw 'Full flash restore mismatch.' }
```

### Connect, read back and repeat a trial

Install the host package. Use `looptrial devices` to identify the USB serial port. Replace `COM8` below with the local port. On Linux a URI might be `serial:///dev/ttyUSB0`. Set `$link` to `'ble://BD-BT26'` to repeat over GATT. Discovery by advertised name or local address must identify exactly one peripheral. Use the address if several devices share a name. Publish only the transport type in shared records. Each connection checks LT1, board model and firmware version.

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

The returned `id` identifies the run. Use `looptrial review <id>` to recompute metrics from CSV. For BLE, the default service is FFE0. The client subscribes to FFE1 and selects a writable characteristic from FFE1 and FFE2. To specify a mapping explicitly, use `'ble://BD-BT26?service=ffe0&notify=ffe1&write=ffe2'`. Allow time for advertising to resume after disconnect. On Windows one command can include several scans and handshakes. The USB path uses a USB-to-UART bridge. The BLE path requires GATT, which classic Bluetooth virtual COM ports do not provide.

### Live observation

The v0.2 firmware produces an observation every 50 ms (20 Hz) using the board clock. During idle operation the model follows an alternating 20/120 count reference with one second per level. During a step it reports the bounded experiment's target and latest response. The observation ring retains 32 samples (1.6 s). The host reads at most four rows per page; successive sequence numbers expose any missed samples. The separate 4–64 point experiment buffer preserves the requested sample period through host delays. A BLE or serial write acknowledged by the device is followed by an independent read of the active gain. The host keeps the caller's last confirmed state and its timestamp when the link fails. A fresh handshake and read are required to confirm the new state.

### Timing, samples and wire protocol

SysTick computes the response on a 1 ms timebase. The main loop sends data. At each sample period the model adds `gain/16` of the remaining error to its output, rounding the increment up to 0.001 count. The first sample arrives after one period. Actions accept 4–64 samples, 10–100 ms periods and targets of 1–1000 count. They finish autonomously within 6.4 s. The board drives no external actuator. Sample time `t` is measured on the board in seconds from the start; host retrieval time and BLE latency do not affect it.

LT1 uses LF-terminated ASCII frames and an independent byte-stream decoder per link. Requests take the form `@<seq> <op> [unsigned decimal arguments...]\n`. Responses are `@<seq> OK [fields...]\n` or `@<seq> ERR <code>\n`. Each peer has one outstanding request. The sequence number associates the reply with its request. A separate nonzero random 32-bit `token` identifies a trial.

| Op | Request arguments | Fields after OK |
|---|---|---|
| H | none | LT1, model, firmware version, unit tag compared on connection |
| R | none | current gain |
| W | gain | gain after write, checked by an independent R |
| S | token target period_ms samples expected_gain | none. Atomically check the expected gain and start. |
| Q | token | state, buffered sample count, gain at start |
| F | token offset | offset, row count, pairs of relative milliseconds and output in thousandths of a count |
| X | token | state after stop, sample count, gain at start |
| T | last continuous sequence, 0 for latest | first sequence, row count (0–4), then target, response in milli-counts and active gain per row. Time in seconds is sequence × 0.05. If the cursor exceeds the current sequence, return `clock_reset`. |

States are 1 running, 2 completed and 3 cancelled. During acquisition, W and a new S return `busy`. Repeating S with the same token and configuration retrieves the original acceptance; conflicting settings return `conflict`. Reset clears the current trial and deduplication history for the last eight replaced tokens. Only the latest trial's sample buffer is retained on the board. The host keeps data by run ID. CLI `--key` independently provides persistent cross-process idempotency. After a transport interruption, the host repeats the handshake, compares the unit tag, then queries and resumes retrieval using the original token. If reset or board replacement prevents recovery, the host records a failure. A cancelled run can return the samples already collected. The protocol is designed for a trusted bench. Serial frames have no authentication or application-level CRC.

The host sends S once per experiment. If the start acknowledgement is lost, it queries the original token with Q. After an MCU reset the bridge may remain reachable while Q returns `unknown_trial`. The run then records failure with unknown device state, distinguishable from a resumed trial.

### Integrate an existing project

1. Check sampling callbacks, variable definitions and control tasks for units, signs, clock source and period. Identify which configuration actually takes effect and when. Start with one read-only signal. Check samples and timestamps against a known steady value or step. Calibration requires an independent reference. Replay supports recalculation from existing records.
2. To implement this example board protocol, port `firmware/looptrial.c` and `looptrial.h`. In the main loop or communication task, pass each port's bytes to `lt_receive(&decoder, byte, send, port)`. Allocate and zero an `lt_decoder` per connection. The `send` callback emits one byte. Call `lt_init(tag)` once with a stable local tag and call `lt_tick()` from a 1 ms periodic context. Keep blocking transmission outside the high-priority control ISR.
3. To retain a device's existing real-time loop and protocol, sample into a preallocated ring or fixed-length buffer. Start the excitation on the board. Enforce device-specific limits, timeout, cancellation and idle state. Validate parameters, commit at a defined loop boundary and read back the active variables. Return buffered pages with timestamps and indices. Implement physical limits and fallback for each real actuator.
4. Register the Python adapter as a `looptrial.devices` entry point. Report the actual firmware identity and version. In `describe`, list signal units and allowable parameters and action ranges. A read-only device exposes empty `parameters`. Map `read/apply/acquire` to the existing protocol. Keep `metrics` dependent only on saved settings, conditions and rows so offline review can reproduce it. Run `looptrial resources` to locate the installed `pressure_adapter` example. CLI and MCP reuse the description. The built-in LT1 host description matches a particular model and version. New firmware needs its own description and validation.

A record's board `instance` alias derives from a private local salt and the handshake tag. USB and BLE connections to the same board share an alias in the same data directory. A different directory yields an independent alias. The example uses a 32-bit unit tag, so collisions are possible. Production firmware can supply a longer tag. [v0.2 workbench and physical link records](../evidence/v02/board/README.en.md) · [v0.1 bench records](../evidence/board/README.en.md)

Pin mapping follows ST RM0008 Rev 21, table 54 on page 181. [ST reference manual](https://www.st.com/resource/en/reference_manual/rm0008-stm32f101xx-stm32f102xx-stm32f103xx-stm32f105xx-and-stm32f107xx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf) · [Module documentation](https://botelvdong.com/courses/Modules/docs/bluetooth/Summary) · [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html) · [BleakClient API](https://bleak.readthedocs.io/en/stable/api/client.html)
