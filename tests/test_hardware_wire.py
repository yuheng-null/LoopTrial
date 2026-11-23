"""Exercise both production transports against the actual C protocol, with a virtual clock."""
import ctypes as ct
import os
from pathlib import Path
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from looptrial import hardware as hw


class Decoder(ct.Structure):
    _fields_ = [("line", ct.c_char * 80), ("used", ct.c_uint), ("discard", ct.c_uint)]


Send = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_char)


@pytest.fixture(scope="module")
def firmware_image(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        pytest.skip("Native C compiler needed to run firmware on this host.")
    path = Path(__file__).resolve().parents[1] / "firmware" / "looptrial.c"
    dll = tmp_path_factory.mktemp("native") / ("firmware.dll" if os.name == "nt" else "firmware.so")
    subprocess.run([compiler, "-std=c11", "-shared", "-fPIC", "-O2", str(path), "-o", str(dll)], check=True)
    return dll


def load_firmware_image(path):
    lib = ct.CDLL(str(path))
    lib.lt_receive.argtypes = [ct.POINTER(Decoder), ct.c_char, Send, ct.c_void_p]
    lib.lt_init.argtypes = [ct.c_uint32]
    return lib


@pytest.fixture
def firmware(firmware_image, tmp_path):
    # A separate loader image gives each test a fresh C BSS, as on power-on.
    return load_firmware_image(shutil.copy(firmware_image, tmp_path))


class Board:
    def __init__(self, lib):
        self.lib = lib
        self.decoder = Decoder()
        self.lib.lt_init(17)
        self.reply = bytearray()
        self.frame = bytearray()
        self.commands = []
        self.drop = self.disconnect = self.bad_read = self.swap = self.gap = False
        self.legacy = False
        self.reboot_image = None

    def feed(self, data):
        response = bytearray()
        for c in data:
            byte = bytes([c])
            self.lib.lt_receive(ct.byref(self.decoder), byte, Send(lambda _, b: response.extend(b)), None)
            if byte != b"\n":
                self.frame.extend(byte)
                continue
            words = self.frame.decode().split()
            self.frame.clear()
            if not words:
                continue
            cmd = words[1]
            self.commands.append(words[1:])
            if self.legacy and cmd == "H":
                response[:] = response.replace(b"0.2.0", b"0.1.0")
            if cmd == "S" and self.drop:
                self.drop = False
                response.clear()
                if self.reboot_image is not None:
                    self.lib = self.reboot_image
                    self.lib.lt_init(17)
                    self.decoder = Decoder()
            if cmd == "R" and self.bad_read:
                response[:] = (words[0] + " OK 1\n").encode()
            if cmd == "F" and self.gap and words[-1] == "6":
                fields = response.split()
                fields[4] = b"999"
                response[:] = b" ".join(fields) + b"\n"
            for _ in range(25):
                self.lib.lt_tick()
            if cmd == "F" and self.disconnect:
                self.disconnect = False
                if self.swap:
                    self.lib.lt_init(18)
                raise OSError("fixture unplugged")
        if response:
            # Decorrelate stream chunk boundaries from frames and interleave an old reply.
            self.reply.extend(b"@0 OK stale\n" + response)


@pytest.fixture(params=["serial://test", "ble://BD-BT26?write=ffe2"])
def endpoint(request, firmware, monkeypatch, tmp_path):
    import bleak
    import serial
    board = Board(firmware)
    monkeypatch.setenv("LOOPTRIAL_HOME", str(tmp_path / "store"))
    monkeypatch.setattr(hw, "_REPLY_TIMEOUT", .08)

    class Serial:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def write(self, data): board.feed(data)
        @property
        def in_waiting(self): return len(board.reply)
        def read(self, n):
            n = min(n, 7)
            part = bytes(board.reply[:n])
            del board.reply[:n]
            return part

    async def discover(**kwargs):
        return {"device": (SimpleNamespace(name="BD-BT26", address="unit"), SimpleNamespace(local_name="BD-BT26"))}

    class Client:
        def __init__(self, *args, **kwargs):
            self.services = self
            self.is_connected = True
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get_service(self, uuid):
            assert uuid.startswith("0000ffe0")
            return self
        def get_characteristic(self, uuid):
            return SimpleNamespace(properties=["write-without-response"] if uuid.startswith("0000ffe2") else ["notify"])
        async def start_notify(self, char, notify): self.notify = notify
        async def write_gatt_char(self, char, data, response):
            assert len(data) <= 20 and response is False
            board.feed(data)
            while board.reply:
                self.notify(None, bytes(board.reply[:7]))
                del board.reply[:7]

    monkeypatch.setattr(serial, "Serial", Serial)
    monkeypatch.setattr(bleak.BleakScanner, "discover", discover)
    monkeypatch.setattr(bleak, "BleakClient", Client)
    return request.param, board


def test_ack_loss_fragmented_fetch_and_reconnect(endpoint):
    uri, board = endpoint
    assert hw.describe(uri)["id"] == "bluepill-step"
    assert hw.apply(uri, {"gain": 8}) == hw.read(uri) == {"gain": 8}
    board.drop = board.disconnect = True
    rows = hw.acquire(uri, "step", {"target": 80, "samples": 8, "period_ms": 10}, {"gain": 8})
    assert [r["t"] for r in rows] == pytest.approx([i/100 for i in range(1, 9)])
    assert rows[0]["response"] == 40
    assert rows[-1]["response"] == pytest.approx(79.688)
    starts = [cmd for cmd in board.commands if cmd[0] == "S"]
    assert len(starts) == 1
    assert any(cmd[0] == "H" for cmd in board.commands[board.commands.index(starts[-1])+2:])


def test_persistent_link_and_continuous_sampling(endpoint):
    uri, board = endpoint
    device = hw.LiveBoard(uri)
    try:
        assert device.describe(uri)["telemetry"]["period_s"] == .05
        assert device.apply(uri, {"gain": 6}) == device.read(uri) == {"gain": 6}
        first = device.telemetry()
        for _ in range(250):
            board.lib.lt_tick()
        next_page = device.telemetry()
        assert len(next_page) == 4 and next_page[0]["seq"] == first[-1]["seq"] + 1
        assert all(row["gain"] == 6 and row["target"] == 20 for row in next_page)
        assert next_page[-1]["t"] - next_page[0]["t"] == pytest.approx(.15)
        captured = device.acquire(uri, "step", {"samples": 4, "period_ms": 20, "target": 100},
                                  {"gain": 6})
        assert len(captured) == 4 and captured[0]["response"] == 37.5
        assert board.commands.count(["H"]) == 1
        for _ in range(2200):
            board.lib.lt_tick()
        assert device.telemetry()[0]["seq"] > next_page[-1]["seq"] + 1
    finally:
        device.close()
    with pytest.raises(hw.HardwareError, match="closed"):
        device.read(uri)


def test_lost_start_ack_followed_by_board_reboot(endpoint, firmware_image, tmp_path):
    uri, board = endpoint
    second = tmp_path / ("rebooted" + firmware_image.suffix)
    board.reboot_image = load_firmware_image(shutil.copy(firmware_image, second))
    board.drop = True
    with pytest.raises(hw.HardwareError) as error:
        hw.acquire(uri, "step", {}, {"gain": 2})
    assert error.value.code == "unknown_trial" and error.value.state_unknown
    starts = [cmd for cmd in board.commands if cmd[0] == "S"]
    assert len(starts) == 1
    assert ["Q", starts[0][1]] in board.commands
    assert error.value.rows == []


def test_readback_and_cancel_prefix(endpoint):
    uri, board = endpoint
    board.bad_read = True
    with pytest.raises(hw.HardwareError, match="board now reports 1") as error:
        hw.apply(uri, {"gain": 5})
    assert error.value.code == "readback_mismatch"
    board.bad_read = False
    assert hw.read(uri) == {"gain": 5}
    with pytest.raises(hw.HardwareError) as error:
        hw.acquire(uri, "step", {"samples": 12, "period_ms": 20}, {"gain": 5}, lambda: True)
    assert error.value.code == "cancelled"
    assert len(error.value.rows) == 1
    assert hw.read(uri) == {"gain": 5}


def test_session_reuses_verified_unit_and_detects_swap(endpoint):
    uri, board = endpoint
    with hw.session(uri):
        unit = hw.describe(uri)
        assert unit["id"] == "bluepill-step"
        assert hw.read(uri) == hw.apply(uri, {"gain": 2})
        assert board.commands.count(["H"]) == 1
        board.disconnect = board.swap = True
        with pytest.raises(hw.HardwareError) as error:
            hw.acquire(uri, "step", {"samples": 4, "period_ms": 10}, {"gain": 2})
        assert error.value.code == "wrong_device" and error.value.state_unknown
        assert len([cmd for cmd in board.commands if cmd[0] == "S"]) == 1
    assert unit["instance"] != hw.describe(uri)["instance"]


def test_bad_timestamp_keeps_only_valid_prefix(endpoint):
    uri, board = endpoint
    board.gap = True
    with pytest.raises(hw.HardwareError) as error:
        hw.acquire(uri, "step", {"samples": 8, "period_ms": 10}, {"gain": 2})
    assert error.value.code == "sample_gap"
    assert len(error.value.rows) == 6
    assert error.value.rows[-1]["t"] == .06


def test_wired_and_radio_report_same_private_alias(endpoint):
    uri, _ = endpoint
    other = "serial://test" if uri.startswith("ble:") else "ble://BD-BT26?write=ffe2"
    first = hw.describe(uri)
    hw.apply(uri, {"gain": 7})
    assert hw.read(other) == {"gain": 7}
    assert hw.describe(other)["instance"] == first["instance"]
    assert first["instance"] != "17"


def test_legacy_workbench_can_capture_without_streaming(endpoint, monkeypatch):
    from looptrial import engine
    from looptrial.live import LiveSession
    uri, board = endpoint
    board.legacy = True
    session = LiveSession()
    monkeypatch.setattr(engine, "runtime", session)
    try:
        session.connect(uri)
        # The legacy device has no telemetry stream. It can still report gain.
        read_count = board.commands.count(["R"])
        deadline = time.monotonic() + 3
        while session.connected and board.commands.count(["R"]) <= read_count and time.monotonic() < deadline:
            time.sleep(.02)
        assert session.connected and board.commands.count(["R"]) > read_count
        assert engine.apply_parameters(uri, {"gain": 6})["verified"] == {"gain": 6}
        trial = engine.run_experiment(uri, "step", conditions={"samples": 4})
        assert trial["status"] == "completed" and engine.review(trial["id"])["samples"] == 4
        assert not any(cmd[0] == "T" for cmd in board.commands)
    finally:
        session.close()


def test_write_attribution_follows_the_board_and_effective_values(endpoint):
    from looptrial import engine
    uri, _ = endpoint
    other = "serial://test" if uri.startswith("ble:") else "ble://BD-BT26?write=ffe2"
    write = engine.apply_parameters(uri, {"gain": 7})
    trial = engine.run_experiment(other, "step", conditions={"samples": 4})
    assert trial["last_parameter_write"]["command_id"] == write["command_id"]
    hw.apply(uri, {"gain": 3})  # An out-of-band adjustment has no LoopTrial receipt.
    trial = engine.run_experiment(uri, "step", conditions={"samples": 4})
    assert trial["parameters"]["gain"] == 3 and "last_parameter_write" not in trial


def test_board_rejects_stale_parameter_snapshot_and_duplicate_conflict(firmware):
    board = Board(firmware)

    def request(text):
        board.feed(("@1 " + text + "\n").encode())
        reply = board.reply.decode().splitlines()[-1]
        board.reply.clear()
        return reply

    assert request("W 17") == "@1 ERR range"
    assert request("S 123 100 10 20 4") == "@1 ERR readback_mismatch"
    assert request("S 123 100 10 20 2") == "@1 OK"
    assert request("S 123 100 10 20 2") == "@1 OK"
    assert request("S 123 300 10 20 2") == "@1 ERR conflict"
    assert request("W 1") == "@1 ERR busy"
    # 4 requests consumed 100 ticks; a restarted trial would contain only 7 samples.
    assert request("Q 123") == "@1 OK 1 10 2"
    assert request("X 123").startswith("@1 OK 3 ")


@pytest.mark.parametrize(("change", "error_code"), [
    ({"samples": 5}, "insufficient_data"), ({"period_ms": 40}, "sample_gap"),
    ({"target": 917}, "condition_mismatch"),
])
def test_offline_conditions_must_match_board_trace(change, error_code):
    conditions = {"samples": 4, "period_ms": 20, "target": 120}
    rows = [{"t": (i+1)*20/1000, "target": 120, "response": y}
            for i, y in enumerate([60, 90, 105, 112.5])]
    assert hw.metrics("serial://device", "step", conditions, rows)["final_error"] == 7.5
    with pytest.raises(hw.HardwareError) as error:
        hw.metrics("serial://device", "step", conditions | change, rows)
    assert error.value.code == error_code
    with pytest.raises(hw.HardwareError) as error:
        hw.metrics("serial://device", "other", conditions, rows)
    assert error.value.code == "unknown_action"
