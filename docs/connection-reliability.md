# Connection reliability

Notes on why the integration used to get stuck disconnected, and what changed.

## Symptoms

- Entities stay unavailable for a long time after the router becomes reachable again
- Reloading the integration does not help
- Whether it works after a full system reboot appears random

## Root cause: statuses nobody handled

`RestAPI` reports its state through `ConnectivityStatus`. The coordinator reacted to those
status changes and drove reconnection from them:

```python
if status == ConnectivityStatus.Connected:      ...
elif status in [ConnectivityStatus.Failed]:     ...   # reconnect once
elif status == ConnectivityStatus.InvalidCredentials: ...
```

But the API sets four other statuses:

| Where | Status set | Handled? |
| ----- | ---------- | -------- |
| `login()` on any connection error (router down, DNS failure, refused) | `NotFound` | **No** |
| `_async_get()` when a request fails | `Disconnected` | **No** |
| `login()` on a terminated session | `Disconnected` | **No** |
| `async_send_heartbeat()` failure | `Disconnected` | **No** |

So the two most common real-world failures — *the router is not up yet* and *the router just
rebooted* — both landed on a status that nothing reacted to. The integration then sat idle
forever. Nothing else would rescue it: `_async_update_data` only did work when both the API and
the WebSocket were already connected, so the polling loop could not recover either.

This is the whole "sometimes works after a reboot" mystery. If Home Assistant's
`EVENT_HOMEASSISTANT_START` fired while the router was still booting, the single login attempt
failed, the status became `NotFound`, and the integration was dead until Home Assistant itself was
restarted. If the router happened to be up first, everything worked.

### Why the retry that did exist was not enough

The one reconnect path — from a WebSocket `Failed` / `NotConnected` — was single shot:

```python
await self._websockets.terminate()
await sleep(WS_RECONNECT_INTERVAL.total_seconds())
await self._api.initialize()
```

If the router was still unreachable 30 seconds later, `_api.initialize()` failed, set `NotFound`,
and there was no second attempt.

## Other issues found

1. **Fire-and-forget tasks.** Signal handlers used
   `loop.create_task(...).__await__()`, keeping no reference to the task. asyncio only holds weak
   references to tasks, so these could be garbage collected mid-execution — including the task that
   *was* the WebSocket listener.
2. **No dead-peer detection on the WebSocket.** `ws_connect` was called without `receive_timeout`
   or `heartbeat`. A router that vanished without closing the TCP connection left
   `async for msg in self._ws` blocked forever while the integration reported itself connected.
   `WS_TIMEOUT` was passed as `timeout=`, and as a `timedelta` rather than seconds.
3. **A missing session id was indistinguishable from an idle connection.** If `SESSION_ID` was not
   captured before the WebSocket subscribed, the router silently ignored the subscription and sent
   nothing at all, forever.
4. **Unbounded connect.** Nothing limited how long establishing the WebSocket could take.
5. **Session leaks.** Both managers created a new `ClientSession` on every reconnect without
   closing the previous one. `_async_get` additionally dropped the session reference on HTTP 403.
6. **Reload races.** `terminate()` only closed the WebSocket. A reconnect task sleeping inside the
   old coordinator would wake up after the reload and drive the *new* coordinator through the
   dispatcher, producing two competing WebSocket connections.
7. **Permanent stop on bad credentials.** `InvalidCredentials` set `update_interval = None`,
   stopping the coordinator for good even after the password was fixed on the router.
8. **A crash in `async_send_heartbeat`.** `datetime.now() - self._last_valid` with `_last_valid`
   still `None` raises on the first call. The method is currently unused, so it never fired.
9. **Entities never reported unavailable.** Nothing overrode `available`, so a disconnected
   integration kept presenting its last known values as current.

## What changed

### A single connection supervisor

Reconnection is no longer driven by status-change callbacks. The coordinator owns one background
task that loops for the lifetime of the config entry:

```
log in if not logged in  ->  fetch data  ->  run the WebSocket until it drops  ->  back off  ->  repeat
```

Every failure, from any cause, falls through to the same backoff and retry. There is no status that
can escape it, because it no longer looks at statuses to decide whether to retry — it always
retries.

Backoff doubles from 5 seconds to a 5 minute ceiling, and resets as soon as a WebSocket session
lasts at least 30 seconds. A connection that keeps failing immediately is treated as a failure and
backed off from, so an unreachable router is not retried every 5 seconds forever.

Invalid credentials retry every 5 minutes instead of stopping, so fixing the password on the router
is enough to recover.

### Startup no longer races the router

`async_setup_entry` now initializes directly instead of deferring to `EVENT_HOMEASSISTANT_START`.
It can, because initialization performs no network access — it sets up the platforms and hands the
connection to the supervisor. Home Assistant starting before the router is no longer a failure
mode, it is just the first few retries.

### The WebSocket cannot hang

- `receive_timeout` of 60 seconds: the router streams statistics continuously, so silence means the
  peer is gone. The listener now ends and the supervisor reconnects.
- A 30 second bound on establishing the connection.
- The connection is refused outright when no `SESSION_ID` is available yet, instead of connecting
  into permanent silence.

### Lifecycle correctness

- The supervisor task is referenced by the config entry (`async_create_background_task`) so it
  cannot be garbage collected, and is cancelled and awaited on unload.
- Both managers close their client session before creating a new one and on termination.
- `async_unload_entry` terminates the supervisor before the platforms are removed, tolerates a
  missing coordinator, and returns the real unload result.
- API cookies are cleared on reconnect so a dead session cannot be reused.

### Belt and braces

`_async_update_data` runs every second regardless of connection state and:

- restarts the supervisor if its task is ever gone (unhandled exception, cancellation)
- logs a warning while disconnected, with both statuses, so the cause is visible in the log
- cancels and replaces the supervisor if it has not come around its loop in 10 minutes, which is
  well past the maximum backoff and therefore means it is genuinely stuck
- closes the WebSocket when the API is not connected but the WebSocket still is (see below)

### Recovering an API that broke on its own

A single failed request marks the API disconnected - `_async_get` gives up after its retries and sets
the status. But the supervisor spends almost all of its life parked in `_websockets.initialize()`,
which only returns when the WebSocket ends, so nothing logged in again while the WebSocket stayed
healthy. One transient REST failure therefore left every entity unavailable until either the socket
happened to drop or the stall watchdog fired ten minutes later - against a router that was reachable
the whole time. That watchdog also logged `made no progress`, which was misleading: the supervisor
was doing exactly what it was written to do.

`_async_update_data` now closes the WebSocket when it finds the API disconnected while the socket is
still up. That releases the supervisor, which comes back round its loop, logs in again and rebuilds
both halves of the connection. The cost of a transient failure is one reconnect.

A status of `Connecting` is left alone, so the check cannot interrupt a login that is in progress.

### Time is measured monotonically

Every interval and timeout - the poll, the heartbeat, the backoff, the stability threshold, the
watchdogs, the removal grace period, the pending switch state - is measured with `time.monotonic()`.

The wall clock is not monotonic. A machine without a real time clock boots with a restored or epoch
time and steps it when NTP first syncs, often seconds after Home Assistant has started. A backwards
step used to make `now - last_update` negative, which stalled the API poll for the length of the
jump, and put `last_connected` in the future, which silenced the watchdog entirely. The end of
daylight saving did a smaller version of the same thing twice a year.

The wall clock is still used where a real timestamp is meant: `Last Restart`, the `lastUpdate` field
and a device's last activity.

### Honest availability

Entities now report `available = False` while the router cannot be reached, and the state is
written when availability changes rather than only when the data changes. Configuration entities
(intervals, unit, the monitored toggles) stay available, since they are Home Assistant side
settings.

## Verifying

`tests/run.sh`. `tests/test_reconnect.py` drives the real supervisor against a scripted fake router
on a virtual clock, so the backoff sequences cost no wall time: router down at startup, router
rebooting mid-session, repeated login failures, a flapping WebSocket, invalid credentials,
termination, and an API that breaks while the WebSocket stays up.

None of it has been verified against real EdgeOS 3.0.1 hardware. Two assumptions in particular are
worth confirming there: that a `receive_timeout` of 60 seconds is comfortably longer than the gap
between streamed messages on an idle router, and that subscribing to `config-change` does not make
the router reject the whole subscription.
