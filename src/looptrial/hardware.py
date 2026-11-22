"""LT1 board endpoint shared by serial and BD-BT26 GATT transports."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, AsyncExitStack, contextmanager
import secrets
import threading
from urllib.parse import parse_qs, unquote, urlsplit


class HardwareError(RuntimeError):
    def __init__(self, code, message, *, rows=None, state_unknown=False):
        super().__init__(message)
        self.code = code
        self.rows = [] if rows is None else rows
        self.state_unknown = state_unknown


def _integer(low, high, default, unit):
    return {"type": "integer", "min": low, "max": high, "default": default, "unit": unit}


SPEC = {
    "id": "bluepill-step", "version": "0.1.0", "source": "board-software-model",
    "description": "Two UART bridges reach one RAM-only, deterministic first-order plant on the MCU.",
    "signals": {"t": {"unit": "s", "description": "Time since board-side start, from SysTick."},
                "target": {"unit": "count"}, "response": {"unit": "count"}},
    "parameters": {"gain": _integer(1, 16, 2, "1/16 per sample")},
    "actions": {"step": {"description": "Start from zero and capture a bounded first-order response.",
                         "metrics": {"final_response": {"unit": "count", "description": "Last measured output."},
                                     "final_error": {"unit": "count", "description": "Target minus last output."},
                                     "mean_absolute_error": {"unit": "count", "description": "Mean absolute tracking error."}},
                         "conditions": {"target": _integer(1, 1000, 100, "count"),
                                        "samples": _integer(4, 64, 20, "sample"),
                                        "period_ms": _integer(10, 100, 20, "ms")}}},
}
_REPLY_TIMEOUT = 1.6


def _validate(values, fields):
    if not isinstance(values, dict) or values.keys() - fields.keys():
        raise HardwareError("invalid_input", "Unknown fields for the declared device.")
    result = {k: v["default"] for k, v in fields.items()}
    for key, value in values.items():
        spec = fields[key]
        if type(value) not in (int, float) or not spec["min"] <= value <= spec["max"] or int(value) != value:
            raise HardwareError("range", f"{key} must be an integer in [{spec['min']}, {spec['max']}].")
        result[key] = int(value)
    return result


def _uuid(value):
    return f"0000{value.lower()}-0000-1000-8000-00805f9b34fb" if len(value) == 4 else value.lower()


@asynccontextmanager
async def _transport(uri):
    target = urlsplit(uri)
    selector = unquote(target.netloc + target.path)
    options = parse_qs(target.query, strict_parsing=True)
    if not selector:
        raise HardwareError("invalid_input", "Specify a port or an advertised BLE device name/address.")
    if target.scheme == "serial":
        import serial
        if options:
            raise HardwareError("invalid_input", "Serial profile uses 9600 baud, 8N1.")
        with serial.Serial(selector, 9600, timeout=0.08, write_timeout=1) as port:
            async def write(data):
                await asyncio.to_thread(port.write, data)

            async def read():
                return await asyncio.to_thread(port.read, max(1, min(256, port.in_waiting)))
            yield write, read
    elif target.scheme == "ble":
        from bleak import BleakClient, BleakScanner
        if options.keys() - {"service", "notify", "write"}:
            raise HardwareError("invalid_input", "Supported BLE options: service, notify, write.")
        # Some UART bridges take several seconds to advertise again after disconnect.
        for scan_seconds in (3, 4, 5):
            devices = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)
            matches = [d for d, adv in devices.values()
                       if selector.casefold() in {d.address.casefold(), (adv.local_name or d.name or "").casefold()}]
            if matches:
                break
        if len(matches) != 1:
            raise HardwareError("ambiguous_device" if matches else "not_found",
                                "Choose one advertised name or specify its local address.")
        async with BleakClient(matches[0], timeout=12) as client:
            service = client.services.get_service(_uuid(options.get("service", ["ffe0"])[0]))
            if not service:
                raise HardwareError("wrong_device", "Declared BLE service is missing.")
            notify = service.get_characteristic(_uuid(options.get("notify", ["ffe1"])[0]))
            tx = None
            for candidate in options.get("write", ["ffe1", "ffe2"]):
                char = service.get_characteristic(_uuid(candidate))
                if char and {"write", "write-without-response"}.intersection(char.properties):
                    tx = char
                    break
            if not notify or not tx:
                raise HardwareError("unsupported_gatt", "Missing notification or writable characteristic.")
            queue = asyncio.Queue()
            await client.start_notify(notify, lambda _, data: queue.put_nowait(bytes(data)))

            async def write(data):
                for i in range(0, len(data), 20):
                    await client.write_gatt_char(tx, data[i:i+20], response="write" in tx.properties)

            async def read():
                if not client.is_connected:
                    raise HardwareError("disconnected", "BLE link lost.", state_unknown=True)
                try:
                    return await asyncio.wait_for(queue.get(), 0.2)
                except TimeoutError:
                    return b""
            yield write, read
    else:
        raise HardwareError("invalid_input", "Use a serial:// or ble:// device URI.")


class _Peer:
    def __init__(self, write, read):
        self.write, self.read = write, read
        self.seq = secrets.randbelow(1000000)
        self.pending = bytearray()

    async def rpc(self, command, attempts=2):
        self.seq += 1
        prefix = f"@{self.seq} ".encode()
        wire = b"\n" + prefix + command.encode("ascii") + b"\n"
        for _ in range(attempts):
            await self.write(wire)
            try:
                async with asyncio.timeout(_REPLY_TIMEOUT):
                    while True:
                        while b"\n" in self.pending:
                            line, _, rest = self.pending.partition(b"\n")
                            self.pending = bytearray(rest)
                            if not line.startswith(prefix):
                                continue
                            words = line[len(prefix):].decode("ascii").split()
                            if words[:1] == ["OK"]:
                                return words[1:]
                            if len(words) == 2 and words[0] == "ERR":
                                raise HardwareError(words[1], f"Device rejected {command[0]} ({words[1]}).",
                                                    state_unknown=words[1] == "unknown_trial")
                            raise HardwareError("bad_frame", "Unexpected response for this request.")
                        self.pending.extend(await self.read())
                        if len(self.pending) > 2048:
                            raise HardwareError("bad_frame", "Oversize response without a matching frame.")
            except TimeoutError:
                continue
        raise HardwareError("timeout", f"No reply to {command[0]} after {attempts} transmission(s).",
                            state_unknown=True)

    async def identify(self):
        fields = await self.rpc("H")
        if len(fields) != 4 or fields[:3] != ["LT1", SPEC["id"], SPEC["version"]] or not fields[3].isdigit():
            raise HardwareError("wrong_device", "Expected the LT1 bluepill-step 0.1.0 firmware.")
        return fields[3]


@asynccontextmanager
async def _open(uri):
    try:
        async with _transport(uri) as (write, read):
            peer = _Peer(write, read)
            tag = await peer.identify()
            yield peer, tag
    except HardwareError:
        raise
    except ImportError as exc:
        raise HardwareError("missing_dependency", f"Install the hardware transport dependency {exc.name}.") from exc
    except (UnicodeError, ValueError, IndexError) as exc:
        raise HardwareError("bad_frame", "Malformed URI or invalid response fields.") from exc
    except Exception as exc:
        # OS errors can contain private addresses/ports. Expose the error class only.
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        detail = type(exc).__name__ + (f" {code}" if code is not None else "")
        raise HardwareError("link_error", f"Device I/O failed ({detail}).",
                            state_unknown=True) from exc


class _Session:
    """One synchronous CLI operation owns one event loop and one verified connection."""
    def __init__(self, uri, runner):
        self.uri, self.runner = uri, runner
        self.stack = AsyncExitStack()
        self.endpoint = None
        self.tag = None

    async def connect(self):
        if self.endpoint is None:
            # Retry link establishment only. The caller has not sent its operation yet.
            for attempt in range(2):
                try:
                    endpoint = await self.stack.enter_async_context(_open(self.uri))
                    break
                except HardwareError as error:
                    if attempt or error.code not in {"link_error", "timeout", "disconnected"}:
                        raise
                    await asyncio.sleep(.4)
            if self.tag is not None and endpoint[1] != self.tag:
                await self.stack.aclose()
                raise HardwareError("wrong_device", "Device identity changed during this operation.",
                                    state_unknown=True)
            self.endpoint = endpoint
            self.tag = endpoint[1]
        return self.endpoint


_local = threading.local()


@contextmanager
def session(uri):
    with asyncio.Runner() as runner:
        scoped = _Session(uri, runner)
        _local.session = scoped
        try:
            yield
        finally:
            try:
                runner.run(scoped.stack.aclose())
            finally:
                del _local.session


def _run(uri, coroutine):
    scoped = getattr(_local, "session", None)
    if scoped and scoped.uri == uri:
        return scoped.runner.run(coroutine)
    with session(uri):
        return _local.session.runner.run(coroutine)


@asynccontextmanager
async def _connect(uri):
    scoped = _local.session
    endpoint = await scoped.connect()
    try:
        yield endpoint
    except BaseException as exc:
        # Close the failed link through its error translator before a recovery read.
        scoped.endpoint = None
        await scoped.stack.__aexit__(type(exc), exc, exc.__traceback__)
        raise


def _ints(fields, n):
    if len(fields) != n or any(not field.isascii() or not field.isdecimal() for field in fields):
        raise HardwareError("bad_frame", "Invalid number or field count in board response.")
    return list(map(int, fields))


async def _operation(uri, operation, params=None):
    async with _connect(uri) as (peer, tag):
        if operation == "describe":
            from .engine import instance_alias
            return SPEC | {"instance": instance_alias("bluepill-step:" + tag)}
        if operation == "apply":
            if not params:
                raise HardwareError("invalid_input", "Specify gain to update volatile RAM.")
            gain = _validate(params, SPEC["parameters"])["gain"]
            _ints(await peer.rpc(f"W {gain}"), 1)
        current = _ints(await peer.rpc("R"), 1)[0]
        if not 1 <= current <= 16:
            raise HardwareError("bad_frame", "Board reported a gain outside its declared range.")
        if operation == "apply" and current != gain:
            raise HardwareError("readback_mismatch", f"Requested {gain}, board now reports {current}.")
        return {"gain": current}


def describe(uri):
    return _run(uri, _operation(uri, "describe"))


def read(uri):
    return _run(uri, _operation(uri, "read"))


def apply(uri, params):
    return _run(uri, _operation(uri, "apply", params))


async def _collect(peer, token, expected, c, rows, cancelled):
    deadline = asyncio.get_running_loop().time() + c["period_ms"] * c["samples"] / 1000 + 3
    while True:
        cancel = cancelled()
        state, count, captured_gain = _ints(await peer.rpc(f"{'X' if cancel else 'Q'} {token}"), 3)
        if captured_gain != expected:
            raise HardwareError("readback_mismatch", "Trial snapshot differs from requested gain.")
        if state not in (1, 2, 3) or count > c["samples"] or count < len(rows):
            raise HardwareError("bad_frame", "Invalid board acquisition state.")
        if state != 1:
            break
        if asyncio.get_running_loop().time() >= deadline:
            await peer.rpc(f"X {token}")
            raise HardwareError("timeout", "Board exceeded trial timeout and acknowledged cancel.")
        await asyncio.sleep(0.08)
    while len(rows) < count:
        fields = await peer.rpc(f"F {token} {len(rows)}")
        offset, n = _ints(fields[:2], 2)
        if offset != len(rows) or not 1 <= n <= min(6, count-offset):
            raise HardwareError("sample_gap", "Missing or misplaced buffer page.")
        data = _ints(fields[2:], n*2)
        for ms, milli in zip(data[::2], data[1::2]):
            if ms != (len(rows) + 1) * c["period_ms"]:
                raise HardwareError("sample_gap", "Device timestamp differs from sample schedule.")
            rows.append({"t": ms/1000, "target": c["target"], "response": milli/1000})
    if state == 3:
        raise HardwareError("cancelled", "Device acknowledged cancellation.")
    if count != c["samples"]:
        raise HardwareError("sample_gap", "Board finished without the requested sample count.")


async def _acquire(uri, action, conditions, params, cancelled):
    if action != "step":
        raise HardwareError("unknown_action", "Board exposes the step action.")
    c = _validate(conditions, SPEC["actions"][action]["conditions"])
    if not params or "gain" not in params:
        raise HardwareError("invalid_input", "Read effective gain before starting the experiment.")
    expected = _validate(params, SPEC["parameters"])["gain"]
    token = secrets.randbelow(2**32-1) + 1
    rows, initial_tag = [], None
    try:
        async with _connect(uri) as (peer, initial_tag):
            # A reset can erase the device's token history without breaking its USB/BLE bridge.
            # After an uncertain start, only ask about this token; replaying S could restart it.
            try:
                await peer.rpc(f"S {token} {c['target']} {c['period_ms']} {c['samples']} {expected}", attempts=1)
            except HardwareError as error:
                if error.code != "timeout":
                    raise
            await _collect(peer, token, expected, c, rows, cancelled)
    except HardwareError as exc:
        if initial_tag is None or exc.code not in {"disconnected", "link_error", "timeout"}:
            exc.rows = rows
            raise
        # Seek the same token on the same board. Never launch a new run on reconnect.
        try:
            async with _connect(uri) as (peer, new_tag):
                if initial_tag != new_tag:
                    raise HardwareError("wrong_device", "Reconnect reached a different board.")
                await _collect(peer, token, expected, c, rows, cancelled)
        except HardwareError as retry:
            retry.rows = rows
            if retry.code not in {"cancelled", "sample_gap", "readback_mismatch"}:
                retry.state_unknown = True
            raise
    return rows


def acquire(uri, action, conditions, params, cancelled=lambda: False):
    return _run(uri, _acquire(uri, action, conditions, params, cancelled))


def metrics(uri, action, conditions, rows):
    if action != "step":
        raise HardwareError("unknown_action", "Board exposes the step action.")
    c = _validate(conditions, SPEC["actions"][action]["conditions"])
    if len(rows) != c["samples"]:
        raise HardwareError("insufficient_data", "Trace length differs from the declared sample count.")
    for i, row in enumerate(rows, 1):
        if row["t"] != (i*c["period_ms"])/1000:
            raise HardwareError("sample_gap", "Trace timestamps differ from the board schedule.")
        if row["target"] != c["target"]:
            raise HardwareError("condition_mismatch", "Recorded target differs from the trial conditions.")
    return {"final_response": rows[-1]["response"],
            "final_error": rows[-1]["target"] - rows[-1]["response"],
            "mean_absolute_error": sum(abs(r["target"] - r["response"]) for r in rows)/len(rows)}
