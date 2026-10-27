"""Two pumps (config entries) on one RS485 gateway share ONE Modbus TCP client
and ONE lock (per-entry clients interleaved frames, "request ask for
id=1 but got id=2"). The last entry to unload closes the shared connection."""
from __future__ import annotations

import asyncio
import types

from test_poll_resilience import mod  # stubbed coordinator module


class _Coord(mod.FoxAirCoordinator):
    # skip DataUpdateCoordinator.__init__ (HA stub); only the gateway wiring matters
    def __init__(self, entry):
        self.entry = entry
        self._gw_key = mod._gw_key(entry.data)
        self._gw = mod.gateway_acquire(entry.data)


def _entry(host, port, slave):
    return types.SimpleNamespace(entry_id=f"{host}-{port}-{slave}",
                                 data={"host": host, "port": port, "slave": slave})


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_same_gateway_shares_client_and_lock():
    async def go():
        mod._GATEWAYS.clear()
        a = _Coord(_entry("10.0.0.5", 4196, 1))
        b = _Coord(_entry("10.0.0.5 ", 4196, 2))   # same gateway, stray space
        c = _Coord(_entry("10.0.0.6", 4196, 1))    # other gateway
        assert a._lock is b._lock
        assert a._lock is not c._lock
        assert await a._ensure_connected(a.entry.data)
        first = a.client
        # b must reuse a's connection, not open a second TCP client
        assert await b._ensure_connected(b.entry.data)
        assert b.client is first
        assert c.client is None

        a.release_gateway()
        assert first.connected, "closing one pump must keep the other's link"
        assert b.client is first
        b.release_gateway()
        assert not first.connected, "last pump unload closes the connection"
        assert ("10.0.0.5", 4196) not in mod._GATEWAYS
        a.release_gateway()   # idempotent: no double release
        c.release_gateway()
        assert not mod._GATEWAYS
    _run(go())


def test_reconfigure_releases_old_gateway():
    """Reconfigure writes the new host into entry.data BEFORE unload: release
    must still drop the gateway the coordinator acquired."""
    async def go():
        mod._GATEWAYS.clear()
        e = _entry("old", 502, 1)
        a = _Coord(e)
        a._gw_key = mod._gw_key(e.data)
        e.data = {"host": "new", "port": 502, "slave": 1}
        a.release_gateway()
        assert not mod._GATEWAYS
    _run(go())


def test_reload_after_last_unload_gets_fresh_gateway():
    async def go():
        mod._GATEWAYS.clear()
        a = _Coord(_entry("gw", 502, 1))
        old_lock = a._lock
        a.release_gateway()
        a2 = _Coord(_entry("gw", 502, 1))
        assert a2._lock is not old_lock
        a2.release_gateway()
    _run(go())
