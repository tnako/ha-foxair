#!/usr/bin/env python3
"""Offline tests for tools/modbus_probe.py against a fake Modbus TCP bridge.

The fake drops the first request after a connect (the USR-DR164/EW11 quirk)
and keeps a register file; tests cover scaled read, verified write with
--restore, --watch until a bit is set, and that no host is baked into the tool.

Run: pytest tests/test_modbus_probe.py -v
"""
import importlib.util
import pathlib
import re
import socket
import struct
import threading
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("modbus_probe", ROOT / "tools/modbus_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
probe.PACE_S = 0


class FakeBridge:
    def __init__(self, regs, on_write=None):
        self.regs = dict(regs)
        self.on_write = on_write
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.srv.accept()
        first = True
        with conn:
            while True:
                hdr = conn.recv(7)
                if len(hdr) < 7:
                    return
                tid, _, length, unit = struct.unpack(">HHHB", hdr)
                pdu = conn.recv(length - 1)
                if first:
                    first = False
                    continue
                fc = pdu[0]
                if fc == 3:
                    addr, count = struct.unpack(">HH", pdu[1:5])
                    words = [self.regs.get(addr + i, 0) for i in range(count)]
                    body = struct.pack(">BB", 3, 2 * count) + b"".join(struct.pack(">H", w) for w in words)
                else:
                    addr, count, _n = struct.unpack(">HHB", pdu[1:6])
                    for i in range(count):
                        self.regs[addr + i] = struct.unpack(">H", pdu[6 + 2 * i:8 + 2 * i])[0]
                    if self.on_write:
                        self.on_write(self.regs, addr)
                    body = struct.pack(">BHH", 16, addr, count)
                conn.sendall(struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body)


def _probe(bridge):
    return probe.Probe("127.0.0.1", bridge.port, 1, timeout=0.3, tries=3)


def test_read_survives_dropped_first_request_and_scales():
    b = FakeBridge({2104: 35, 1250: 450, 2033: 32767})
    p = _probe(b)
    try:
        assert p.read(2104) == [35]
        sc = probe.Scaler(raw=False)
        assert sc.to_value(1250, p.read(1250)[0]) == 45.0
        assert sc.to_raw(1464, 18.0) == 180
        assert probe.Scaler(raw=True).to_value(1250, 450) == 450
    finally:
        p.close()


def test_write_verify_watch_and_restore():
    def effect(regs, addr):
        if addr == 1255 and regs.get(1236) == 2:
            regs[2014] = regs[1255]

    b = FakeBridge({1236: 2, 1255: 450, 2014: 450}, on_write=effect)
    p = _probe(b)
    args = types.SimpleNamespace(assignments=["1255=23.5"], watch=2014, until_bit=None,
                                 timeout=2, interval=0.05, restore=True)
    try:
        assert probe.cmd_write(p, probe.Scaler(raw=False), args) == 0
        assert b.regs[1255] == 450 and b.regs[2014] == 450
    finally:
        p.close()


def test_watch_until_bit_times_out_with_rc2_and_still_restores():
    b = FakeBridge({1464: 600, 1465: 0, 2146: 0x22C})
    p = _probe(b)
    args = types.SimpleNamespace(assignments=["1464=18.0", "1465=1"], watch=2146, until_bit=4,
                                 timeout=0.3, interval=0.05, restore=True)
    try:
        assert probe.cmd_write(p, probe.Scaler(raw=False), args) == 2
        assert (b.regs[1464], b.regs[1465]) == (600, 0)
    finally:
        p.close()


def test_single_glitched_zero_is_not_an_effect():
    b = FakeBridge({1234: 0, 2014: 200})
    reads = iter([200, 200, 0, 200, 200, 200] + [200] * 200)
    real = probe.Probe.read

    def fake_read(self, addr, count=1, unit=None):
        if addr == 2014:
            return [next(reads)]
        return real(self, addr, count, unit)

    p = _probe(b)
    args = types.SimpleNamespace(assignments=["1234=1.5"], watch=2014, until_bit=None,
                                 timeout=0.4, interval=0.05, restore=True)
    try:
        probe.Probe.read = fake_read
        assert probe.cmd_write(p, probe.Scaler(raw=False), args) == 2
        assert b.regs[1234] == 0
    finally:
        probe.Probe.read = real
        p.close()


def test_no_host_or_ip_in_tool():
    src = (ROOT / "tools/modbus_probe.py").read_text()
    assert not re.search(r"\b(?:192\.168|10|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b", src)
    assert 'env.get("MODBUS_HOST")' in src
