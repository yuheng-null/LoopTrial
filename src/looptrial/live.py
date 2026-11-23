"""One live connection per workbench. Hardware clocks and host arrivals stay distinct."""

from collections import deque
import contextlib
import threading
import time
import uuid

from . import engine, models


class LiveSession:
    def __init__(self):
        self.transition = threading.RLock()
        self.lock = threading.RLock()
        self.uri = self.board = self.info = self.last_confirmed = None
        self.session_id = self.error = self.thread = None
        self.connected = False
        self.stop = threading.Event()
        self.values = {}
        self.rows = deque(maxlen=600)
        self.reset_stats()

    def reset_stats(self):
        self.updates = self.samples = self.missing = 0
        self.first_host = self.last_host = self.first_device = None
        self.last_seq = self.first_seq = None
        self.max_gap = 0.0
        self.rows.clear()

    def board_for(self, uri):
        with self.lock:
            if self.uri == uri:
                if self.connected and self.board is not None:
                    return self.board
                raise engine.Problem("disconnected", "Reconnect the workbench and confirm the device first.")
            if self.board is not None:
                raise engine.Problem("device_busy", "The workbench already owns a physical endpoint. Switch connections first.")
            return None

    def active(self):
        if self.uri:
            with engine.database() as db:
                row = db.execute("SELECT id FROM jobs WHERE resource=? AND status IN ('queued','running')",
                                 (engine.resource(self.uri),)).fetchone()
            if row and engine.get_run(row[0])["status"] in ("queued", "running"):
                return row[0]
        return None

    def disconnect(self):
        with self.transition:
            if self.active():
                raise engine.Problem("device_busy", "Stop the active experiment before disconnecting.")
            self.close()
            return self.snapshot()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
            self.thread = None
        try:
            if self.board is not None:
                self.board.close()
        finally:
            with self.lock:
                was_connected = self.connected
                self.connected, self.board = False, None
                if was_connected:
                    engine.observe(self.uri, "disconnected", {"last_confirmed": self.last_confirmed})

    def connect(self, uri):
        with self.transition:
            if self.uri == uri and self.connected:
                return self.snapshot()
            if self.active():
                raise engine.Problem("device_busy", "Stop the active experiment before switching devices.")
            self.close()
            physical = uri.startswith(("serial://", "ble://"))
            if physical:
                from .hardware import LiveBoard
            previous = self.info if self.uri == uri else None
            with self.lock:
                if uri != self.uri:
                    self.last_confirmed = None
                self.session_id = uuid.uuid4().hex
                self.uri, self.info, self.error = uri, previous, None
                self.reset_stats()
                self.stop = threading.Event()
            board = None
            try:
                with engine.lock_for("device/" + engine.resource(uri), timeout=5):
                    board = LiveBoard(uri) if physical else None
                    adapter = board or engine.backend(uri)
                    info = engine.identify(adapter, uri)
                    if previous and previous.get("instance") != info.get("instance"):
                        raise engine.Problem("wrong_device", "Reconnected endpoint identifies a different device.")
                    values = engine._read(adapter, uri, info)
                with self.lock:
                    self.board, self.info, self.connected = board, info, True
                    self.values = dict(values)
                    self.confirm(uri, values)
                engine.observe(uri, "connected", {"device": info["id"], "version": info["version"], "values": values})
                if board or uri.startswith("sim://"):
                    self.thread = threading.Thread(target=self.poll, daemon=True, name="looptrial-telemetry")
                    self.thread.start()
            except Exception as error:
                if board:
                    with contextlib.suppress(Exception):
                        board.close()
                self.unknown(uri, str(error))
                raise
            return self.snapshot()

    def confirm(self, uri, values, stamp=None):
        with self.lock:
            if self.uri == uri and self.connected:
                self.values.update(values)
                self.last_confirmed = {"time": stamp or engine.now(), "values": dict(values)}

    def unknown(self, uri, message):
        with self.lock:
            if self.uri == uri:
                self.connected, self.error = False, message
                self.stop.set()
                engine.observe(uri, "unknown", {"error": message, "last_confirmed": self.last_confirmed})

    def poll(self):
        token = engine.actor.set("device")
        try:
            started = time.monotonic()
            i = 0
            if self.board is None:
                period, stream = models.live_samples(self.uri, self.values)
            while not self.stop.is_set():
                if self.board:
                    batch = self.board.telemetry()
                else:
                    elapsed = time.monotonic() - started
                    batch = []
                    while i * period <= elapsed and len(batch) < 100:
                        batch.append({"seq": i, **next(stream)})
                        i += 1
                if batch:
                    self.accept(batch)
                self.stop.wait(.1)
        except Exception as error:
            if not self.stop.is_set():
                self.unknown(self.uri, str(error))
        finally:
            engine.actor.reset(token)

    def accept(self, batch):
        with self.lock:
            host = time.monotonic()
            fresh = 0
            for row in batch:
                seq = row["seq"]
                if seq == self.last_seq:
                    continue
                if self.last_seq is not None:
                    if seq < self.last_seq or row["t"] <= self.rows[-1]["t"]:
                        raise ValueError("Device clock or sample sequence restarted. Reconnect to start a new time axis.")
                    self.missing += seq - self.last_seq - 1
                else:
                    self.first_device = row["t"]
                    self.first_seq = seq
                self.rows.append(dict(row))
                self.last_seq = seq
                fresh += 1
            if fresh:
                self.samples += fresh
                self.updates += 1
                if self.last_host is not None:
                    self.max_gap = max(self.max_gap, host - self.last_host)
                if self.first_host is None:
                    self.first_host = host
                self.last_host = host

    def snapshot(self):
        with self.lock:
            host_span = self.last_host - self.first_host if self.first_host is not None else 0
            device_span = self.rows[-1]["t"] - self.first_device if self.rows else 0
            uri = self.uri
            result = {"uri": uri, "session_id": self.session_id, "connected": self.connected,
                      "info": self.info, "error": self.error, "state": "verified" if self.connected else "unknown",
                      "values": dict(self.values) if self.connected else None, "last_confirmed": self.last_confirmed,
                      "stream": list(self.rows), "stats": {"updates": self.updates, "samples": self.samples,
                      "missing": self.missing, "max_gap_s": self.max_gap,
                      "age_s": time.monotonic() - self.last_host if self.last_host is not None else None,
                      "update_hz": (self.updates-1)/host_span if host_span else 0,
                      "sample_hz": (self.last_seq-self.first_seq)/device_span if device_span else 0}}
        return result | {"events": engine.timeline(uri) if uri else [], "active_run": self.active()}
