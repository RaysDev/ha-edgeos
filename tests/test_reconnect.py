"""Drive the real connection supervisor against a scriptable fake router.

Reproduces the failure scenarios reported against the integration and asserts
that the supervisor recovers from each one.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.edgeos.common.connectivity_status import (  # noqa: E402
    ConnectivityStatus,
)
from custom_components.edgeos.managers import (  # noqa: E402
    coordinator as coordinator_module,
)
from custom_components.edgeos.managers.coordinator import Coordinator  # noqa: E402

ok = True


def check(label, actual, expected):
    global ok
    passed = actual == expected
    ok &= passed
    print(
        f"[{'PASS' if passed else 'FAIL'}] {label}: {actual!r}"
        + ("" if passed else f" != {expected!r}")
    )


def check_true(label, value):
    check(label, bool(value), True)


# --- a virtual clock so backoff sleeps cost no wall time --------------------
class Clock:
    def __init__(self):
        self.now = 1_000_000.0
        self.slept = []

    async def sleep(self, delay):
        self.slept.append(delay)
        self.now += delay
        await asyncio.sleep(0)

    def advance(self, seconds):
        self.now += seconds


CLOCK = Clock()


def fake_monotonic():
    """Stands in for `time.monotonic`, driven by the virtual clock above."""
    return CLOCK.now


class FakeAPI:
    """Fake RestAPI. `script` decides what each login attempt does."""

    def __init__(self, script, update_script=None):
        self.script = list(script)
        self.update_script = list(update_script or [])
        self.status = None
        self.data = {"session-id": "abc"}
        self.login_attempts = 0
        self.updates = 0
        self.terminated = False

    async def initialize(self):
        self.login_attempts += 1
        outcome = self.script.pop(0) if self.script else "connect"

        if outcome == "raise":
            self.status = ConnectivityStatus.NotFound
            raise ConnectionRefusedError("router is not up")
        if outcome == "notfound":
            self.status = ConnectivityStatus.NotFound
        elif outcome == "disconnected":
            self.status = ConnectivityStatus.Disconnected
        elif outcome == "badcreds":
            self.status = ConnectivityStatus.InvalidCredentials
        else:
            self.status = ConnectivityStatus.Connected

    async def update(self):
        self.updates += 1
        outcome = self.update_script.pop(0) if self.update_script else "ok"

        # What the real RestAPI does when a request fails: `_async_get` gives up
        # after its retries and flips the status to Disconnected
        if outcome == "fail":
            self.status = ConnectivityStatus.Disconnected

    async def terminate(self):
        self.terminated = True


class FakeWebSockets:
    """Fake WebSockets. `script` decides how long each session lasts, in seconds."""

    def __init__(self, script):
        self.script = list(script)
        self.status = None
        self.connections = 0
        self.terminations = 0

    def update_api_data(self, api_data, can_log):
        pass

    async def initialize(self):
        self.connections += 1
        duration = self.script.pop(0) if self.script else 0

        if duration <= 0:
            self.status = ConnectivityStatus.Failed
        else:
            self.status = ConnectivityStatus.Connected
            CLOCK.advance(duration)
            self.status = ConnectivityStatus.NotConnected

        await asyncio.sleep(0)

    async def terminate(self):
        self.terminations += 1
        self.status = ConnectivityStatus.Disconnected


class FakeConfigManager:
    log_incoming_messages = False


class FakeCoordinator:
    """Duck typed `self` so the real supervisor code runs unmodified."""

    _get_reconnect_delay = Coordinator._get_reconnect_delay

    def __init__(
        self, api_script, ws_script, stop_after_loops=None, update_script=None
    ):
        self._api = FakeAPI(api_script, update_script)
        self._websockets = FakeWebSockets(ws_script)
        self._config_manager = FakeConfigManager()
        self._is_terminated = False
        self._last_connected = 0
        self._loops = 0
        self._stop_after_loops = stop_after_loops

    @property
    def is_terminated(self):
        # Stops the otherwise infinite supervisor loop after N iterations
        if self._stop_after_loops is not None and self._loops >= self._stop_after_loops:
            return True
        return self._is_terminated


class DisconnectableWebSockets:
    """Records whether the coordinator asked for the socket to be closed."""

    def __init__(self, status):
        self.status = status
        self.disconnects = 0

    async def async_disconnect(self):
        self.disconnects += 1


class RecoveryCoordinator:
    """Duck typed `self` for `_recover_broken_api`."""

    def __init__(self, api_status, ws_status):
        self._api = FakeAPI([])
        self._api.status = api_status
        self._websockets = DisconnectableWebSockets(ws_status)


async def run(fake, loops):
    """Run the real supervisor for a bounded number of iterations."""
    fake._stop_after_loops = loops

    original_sleep = coordinator_module.sleep
    original_monotonic = coordinator_module.monotonic

    async def counting_sleep(delay):
        fake._loops += 1
        fake._is_terminated = fake.is_terminated
        await CLOCK.sleep(delay)

    coordinator_module.sleep = counting_sleep
    coordinator_module.monotonic = fake_monotonic

    try:
        await asyncio.wait_for(Coordinator._connection_supervisor(fake), timeout=10)
    finally:
        coordinator_module.sleep = original_sleep
        coordinator_module.monotonic = original_monotonic


async def main():
    # --- Scenario A: router is down when Home Assistant starts ---------------
    # This is the "sometimes works, sometimes doesn't after a full reboot" case.
    # login raises, which used to set NotFound - a status nothing handled.
    CLOCK.slept = []
    fake = FakeCoordinator(
        api_script=["raise", "raise", "raise", "connect"],
        ws_script=[120],
    )
    await run(fake, loops=4)
    check("A router down at start - login retried", fake._api.login_attempts >= 4, True)
    check("A eventually connected", fake._api.status, ConnectivityStatus.Connected)
    check("A websocket was established", fake._websockets.connections, 1)

    # --- Scenario B: router reboots while connected --------------------------
    # The API request fails and the status becomes Disconnected, which used to
    # be a status nothing reacted to, leaving the integration idle forever.
    CLOCK.slept = []
    fake = FakeCoordinator(
        api_script=["connect", "connect"],
        update_script=["ok", "fail", "ok"],
        ws_script=[300, 300],
    )
    await run(fake, loops=3)
    check(
        "B reconnected after router reboot",
        fake._api.status,
        ConnectivityStatus.Connected,
    )
    check("B logged in again after Disconnected", fake._api.login_attempts, 2)
    check("B websocket re-established", fake._websockets.connections, 2)

    # --- Scenario C: long healthy session drops -> prompt reconnect ----------
    CLOCK.slept = []
    fake = FakeCoordinator(api_script=["connect"] * 3, ws_script=[600, 600, 600])
    await run(fake, loops=3)
    check("C stable session reconnects at minimum delay", CLOCK.slept, [5.0, 5.0, 5.0])

    # --- Scenario D: router unreachable -> exponential backoff, capped ------
    CLOCK.slept = []
    fake = FakeCoordinator(api_script=["raise"] * 12, ws_script=[])
    await run(fake, loops=12)
    check(
        "D backoff grows and caps at 300s",
        CLOCK.slept,
        [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0, 300.0, 300.0, 300.0],
    )
    check("D never stops retrying", fake._api.login_attempts, 12)

    # --- Scenario E: websocket keeps failing immediately --------------------
    # Without the stability threshold this would retry every 5s forever.
    CLOCK.slept = []
    fake = FakeCoordinator(api_script=["connect"] * 6, ws_script=[0] * 6)
    await run(fake, loops=6)
    check(
        "E flapping websocket backs off",
        CLOCK.slept,
        [5.0, 10.0, 20.0, 40.0, 80.0, 160.0],
    )

    # --- Scenario F: bad credentials retry slowly but never give up ---------
    CLOCK.slept = []
    fake = FakeCoordinator(api_script=["badcreds"] * 3, ws_script=[])
    await run(fake, loops=3)
    check(
        "F invalid credentials retried at 5 minutes", CLOCK.slept, [300.0, 300.0, 300.0]
    )
    check("F kept trying", fake._api.login_attempts, 3)

    # --- Scenario G: terminate stops the loop -------------------------------
    CLOCK.slept = []
    fake = FakeCoordinator(api_script=["connect"], ws_script=[600])
    fake._is_terminated = True
    await run(fake, loops=5)
    check("G terminated supervisor does nothing", fake._api.login_attempts, 0)

    # --- Scenario H: API recovers without a full restart of the websocket ---
    CLOCK.slept = []
    fake = FakeCoordinator(
        api_script=["notfound", "notfound", "connect"],
        ws_script=[600],
    )
    await run(fake, loops=3)
    check("H recovers from NotFound", fake._api.status, ConnectivityStatus.Connected)
    check("H websocket connected once recovered", fake._websockets.connections, 1)

    # --- Scenario I: API breaks while the websocket stays up ----------------
    # The supervisor is parked on the websocket and only logs in again once it
    # ends, so nothing recovered the API until the stall watchdog fired ten
    # minutes later. The coordinator now closes the websocket to release it.
    for label, api_status, ws_status, expected in [
        (
            "broken API closes the websocket",
            ConnectivityStatus.Disconnected,
            ConnectivityStatus.Connected,
            1,
        ),
        (
            "bad credentials close the websocket",
            ConnectivityStatus.InvalidCredentials,
            ConnectivityStatus.Connected,
            1,
        ),
        (
            "a healthy API is left alone",
            ConnectivityStatus.Connected,
            ConnectivityStatus.Connected,
            0,
        ),
        (
            "an API mid-login is left alone",
            ConnectivityStatus.Connecting,
            ConnectivityStatus.Connected,
            0,
        ),
        (
            "nothing to close when the websocket is already gone",
            ConnectivityStatus.Disconnected,
            ConnectivityStatus.NotConnected,
            0,
        ),
    ]:
        recovery = RecoveryCoordinator(api_status, ws_status)
        await Coordinator._recover_broken_api(recovery)
        check(f"I {label}", recovery._websockets.disconnects, expected)

    print()
    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
