#!/usr/bin/env python3
"""Offline poll-loop resilience tests (no HA / pymodbus installed).

Regression: a single dead Modbus batch must not abort the whole poll
cycle (the 2026-09-18 user file showed 15 timeouts wiping all 269 rare
addrs incl. H31). Policy under test:
- tier-ordered batches: quick first, then medium, then rare
- reconnect-and-continue on connection errors, abort only after 3 in a row
- 0.35s EW11 pacing between reads

The coordinator module is loaded with HA + pymodbus stubbed; helper
functions (scaled, _apply_config) come from the real source.
"""
import asyncio
import importlib.util
import pathlib
import re
import sys
import types
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules():
    ha = types.ModuleType("homeassistant")
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, name=None, update_interval=None):
            self.hass = hass

    ha.uc.DataUpdateCoordinator = DataUpdateCoordinator

    class UpdateFailed(Exception):
        pass

    ha.uc.UpdateFailed = UpdateFailed
    ha.exc = types.ModuleType("homeassistant.exceptions")

    class ConfigEntryNotReady(Exception):
        pass

    ha.exc.ConfigEntryNotReady = ConfigEntryNotReady
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.helpers"] = ha.helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = ha.uc
    sys.modules["homeassistant.exceptions"] = ha.exc

    pm = types.ModuleType("pymodbus")
    pmc = types.ModuleType("pymodbus.client")

    class AsyncModbusTcpClient:
        created = 0

        def __init__(self, *a, **k):
            type(self).created += 1
            self.connected = True

        async def connect(self):
            return True

        def close(self):
            self.connected = False

    pmc.AsyncModbusTcpClient = AsyncModbusTcpClient
    pm.client = pmc
    sys.modules["pymodbus"] = pm
    sys.modules["pymodbus.client"] = pmc

    # const stub: real _apply_dict logic unnecessary — tests inject sets.
    const = types.ModuleType("foxair_poll_const")

    def word_mask(bits):
        return 0

    const.word_mask = word_mask
    const.CORE_MAIN_ADDRS = set()
    const.MEDIUM_INTERVAL = 4
    const.RARE_INTERVAL = 10
    const.MODBUS_MAX_SPAN = 100
    const.MODBUS_MAX_GAP = 30
    sys.modules["foxair_poll_const"] = const
    return const


_const_stub = _stub_modules()

_src = (CC / "coordinator.py").read_text()
_src = _src.replace("from .const import (", "from foxair_poll_const import (")
_src = _src.replace("from . import const as _const",
                    "import foxair_poll_const as _const")
_src = _src.replace("from . import computed as _computed",
                    "import foxair_poll_computed as _computed")
# computed stub: energy accumulation helpers unused by these tests.
_comp_stub = types.ModuleType("foxair_poll_computed")
_comp_stub.active_mode = lambda coord: None
_comp_stub.compute_thermal_power = lambda coord, mode: None
_comp_stub.compute_cooling_power = lambda coord: None
_comp_stub.compute_electrical_power = lambda coord, opts: None
sys.modules["foxair_poll_computed"] = _comp_stub
mod = types.ModuleType("foxair_coord_test")
sys.modules["foxair_coord_test"] = mod
mod.__dict__["__file__"] = str(CC / "coordinator.py")
spec = importlib.util.spec_from_file_location("foxair_coord_test",
                                              CC / "coordinator.py")
exec(compile(_src, str(CC / "coordinator.py"), "exec"), mod.__dict__)


class FakeEntry:
    def __init__(self):
        self.entry_id = "e1"
        self.data = {"host": "h", "port": 502, "slave": 1, "name_prefix": "t"}
        self.options = {"enable_expert": False}


class FakeHass:
    pass


class FakeResp:
    def __init__(self, regs=None, error=False):
        self.registers = regs or []
        self._error = error

    def isError(self):
        return self._error


class FlakyClient:
    """Fails batch starting at `fail_start` with No-response, else answers."""

    instances = []

    def __init__(self, *a, **k):
        self.connected = True
        FlakyClient.instances.append(self)

    async def connect(self):
        return True

    def close(self):
        self.connected = False

    async def read_holding_registers(self, address=None, count=0, **kw):
        if address == FlakyClient.fail_start:
            raise Exception("Modbus Error: [Input/Output] No response "
                            "received after 3 retries, continue with next request")
        return FakeResp(regs=[7] * count)


def _make_coord(tier_map):
    coord = mod.FoxAirCoordinator.__new__(mod.FoxAirCoordinator)
    coord.hass = FakeHass()
    coord.entry = FakeEntry()
    coord.client = FlakyClient()
    coord.data = {}
    coord.stats = {"polls": 0, "errors": 0, "last_ms": 0, "quick_polls": 0,
                   "medium_polls": 0, "rare_polls": 0}
    coord._regmap = {str(a): {"type": "RAW"} for tier in tier_map.values()
                     for a in tier}
    coord._metadata = {}
    coord._lock = asyncio.Lock()
    coord._poll_counter = 19  # +=1 -> 20: divisible by medium(4) and rare(10)
    coord._fw_version = 0
    coord._medium_done = True
    coord._rare_done = True
    coord._burst_task = True  # skip startup-burst branch (needs hass)
    coord._tier_map = tier_map
    coord._tier_addrs = lambda tier, expert: set(coord._tier_map[tier])  # noqa: E731
    import foxair_poll_const as c
    coord._batches_for_addrs = (
        lambda addrs: mod.FoxAirCoordinator._batches_for_addrs(coord, set(addrs)))
    c.CORE_MAIN_ADDRS = set()
    return coord


def _run(coro):
    return asyncio.run(coro)


def test_reconnect_and_continue_after_single_failure():
    FlakyClient.instances.clear()
    tiers = {"quick": {1011, 1012}, "medium": {2019}, "rare": {1041}}
    coord = _make_coord(tiers)
    FlakyClient.fail_start = 2019  # medium batch dies
    _run(mod.FoxAirCoordinator._async_update_data(coord))
    # quick (before failure) AND rare (after reconnect) both present
    assert 1011 in coord.data and 1012 in coord.data
    assert 1041 in coord.data
    assert coord.stats["errors"] == 1
    # Failure attributes to the dying tier only.
    assert coord.stats["medium_errors"] == 1
    assert coord.stats.get("quick_errors", 0) == 0
    assert coord.stats.get("rare_errors", 0) == 0


def test_abort_after_three_consecutive_failures():
    FlakyClient.instances.clear()
    tiers = {"quick": {1011}, "medium": {2019}, "rare": {1041, 1042}}
    coord = _make_coord(tiers)
    # force every batch to fail: fail_start matches all starts
    orig = FlakyClient.read_holding_registers

    async def always_fail(self, address=None, count=0, **kw):
        raise Exception("No response received after 3 retries")

    FlakyClient.read_holding_registers = always_fail
    try:
        _run(mod.FoxAirCoordinator._async_update_data(coord))
    finally:
        FlakyClient.read_holding_registers = orig
    assert coord.data == {}
    assert coord.stats["errors"] >= 3


def test_tier_order_quick_first():
    FlakyClient.instances.clear()
    tiers = {"quick": {5000}, "medium": {100}, "rare": {200}}
    coord = _make_coord(tiers)
    FlakyClient.fail_start = -1  # nothing fails
    seen = []
    orig = FlakyClient.read_holding_registers

    async def record(self, address=None, count=0, **kw):
        seen.append(address)
        return await orig(self, address=address, count=count, **kw)

    FlakyClient.read_holding_registers = record
    try:
        _run(mod.FoxAirCoordinator._async_update_data(coord))
    finally:
        FlakyClient.read_holding_registers = orig
    # Tier-ordered: quick batch first even though its addr sorts last.
    assert seen == [5000, 100, 200], seen


def test_per_tier_error_counters():
    # quick batch (1011+1012 merge into one) and rare batch die once each,
    # medium stays clean — errors attribute per tier.
    FlakyClient.instances.clear()
    tiers = {"quick": {1011, 1012}, "medium": {2019}, "rare": {1041}}
    coord = _make_coord(tiers)
    orig = FlakyClient.read_holding_registers

    async def fail_quick_and_rare(self, address=None, count=0, **kw):
        if address in (1011, 1041):
            raise Exception("No response received after 3 retries")
        return FakeResp(regs=[7] * count)

    FlakyClient.read_holding_registers = fail_quick_and_rare
    try:
        _run(mod.FoxAirCoordinator._async_update_data(coord))
    finally:
        FlakyClient.read_holding_registers = orig
    assert coord.stats["errors"] == 2
    assert coord.stats["quick_errors"] == 1
    assert coord.stats.get("medium_errors", 0) == 0
    assert coord.stats["rare_errors"] == 1


def test_read_pacing_is_035():
    lines = (CC / "coordinator.py").read_text().splitlines()
    checked = 0
    for i, line in enumerate(lines):
        if "read_holding_registers" not in line:
            continue
        # find the pacing sleep above this read (within 10 lines back)
        window = "\n".join(lines[max(0, i - 10):i])
        m = re.search(r"await asyncio\.sleep\((0\.\d+)\)", window)
        assert m, f"no pacing sleep before read at line {i + 1}"
        assert float(m.group(1)) >= 0.35, \
            f"read pacing {m.group(1)} < 0.35 before line {i + 1}"
        checked += 1
    assert checked >= 1


def test_single_shared_read_loop():
    """The tiered poll and burst fetch must both delegate to _read_batches."""
    src = (CC / "coordinator.py").read_text()
    assert "_read_batches" in src
    for caller in ("_async_update_data", "_fetch_addrs"):
        body = src.split(f"async def {caller}", 1)[1].split("async def", 1)[0]
        assert "_read_batches(" in body, f"{caller} must delegate to _read_batches"
        assert "read_holding_registers" not in body, f"{caller} has its own read loop"


def test_last_seen_stamped_on_success():
    FlakyClient.instances.clear()
    tiers = {"quick": {1011, 1012}, "medium": {2019}, "rare": {1041}}
    coord = _make_coord(tiers)
    FlakyClient.fail_start = 2019  # medium batch dies
    _run(mod.FoxAirCoordinator._async_update_data(coord))
    assert 1011 in coord._last_seen and 1041 in coord._last_seen
    assert 2019 not in coord._last_seen


def test_staleness_policy():
    tiers = {"quick": {1011}, "medium": {2019}, "rare": {1041}}
    coord = _make_coord(tiers)
    FlakyClient.fail_start = -1
    _run(mod.FoxAirCoordinator._async_update_data(coord))
    coord._metadata = {"1011": {"poll_tier": "quick"}}
    assert not coord.is_stale(1011)
    assert not coord.is_stale(9999)
    import time as _time
    coord._last_seen[1011] = _time.monotonic() - 300
    assert coord.is_stale(1011)
    s = coord.freshness_summary()
    assert s["tracked"] >= 1 and 1011 in s["stale_addrs"]
