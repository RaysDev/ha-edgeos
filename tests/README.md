# Tests

```
tests/run.sh
```

Nothing has to be installed and no router has to be reachable. `hastub.py` stubs the Home Assistant and
aiohttp modules that the integration imports at module level, so the real code under
`custom_components/edgeos` is exercised against scripted fake routers. Each suite resolves the package from
the repository it lives in, and exits non-zero on the first failed assertion set.

| Suite | Covers |
| ----- | ------ |
| `test_imports.py` | That every module in the package imports, and that each platform Home Assistant is asked to set up exists and offers `async_setup_entry`. Home Assistant loads an integration by importing it, so a name left behind by an edit takes the whole thing down before an entity exists |
| `test_firewall.py` | Rule discovery and parsing against realistic `get.json` payloads - IPv4 and IPv6 rule-sets, the valueless `disable` node, a rule-set with no rules, and a rule deleted on the router |
| `test_naming.py` | How a rule-set device and its rule entities are named and identified, and that the identifier is computed apart from the display name so rewording it cannot orphan a device |
| `test_entities.py` | Which entity descriptions are produced per platform for admin and non-admin users, and the exact `set.json` / `delete.json` payload a toggle sends |
| `test_reconnect.py` | The real connection supervisor against a scriptable fake router: the router down at startup, a mid-session reboot, invalid credentials, a WebSocket that never completes its upgrade, a supervisor that stalls, and an API that breaks while the WebSocket stays up |
| `test_events.py` | The `config-change` subscription, the signal it raises, the configuration refresh it triggers, and the pending state that stops a toggled switch bouncing back |
| `test_lifecycle.py` | Rules being added, removed, renumbered and renamed; the removal grace period; a rule that comes back inside the window; and the guard that stops an unread configuration looking like a mass deletion |
| `test_processing.py` | The split between deriving the configuration and deriving statistics: that a statistics message no longer walks the configuration, that it still updates the statistics and discovers interfaces which only appear in the stream, and that it falls back to a full pass before the configuration has been derived once |
| `test_devices.py` | A device's address being followed when it changes, the stale mapping being dropped, the hostname deliberately not being followed, the lease flag only ever clearing, and leased devices being counted on a router with no shared network configured |
| `test_config.py` | Stored intervals being clamped so that a zero cannot busy-loop the coordinator, credentials being stripped from the store without raising, and no action being returned for an item the router no longer has |
| `test_device_monitoring.py` | The shared monitoring device: where each entity of a device lands, that an unmonitored device produces none of its own, hostname naming, and the removal of a device once nothing points at it |
| `test_firmware.py` | The update entity: version strings, and that an update is reported only when the router says so - a router that has never checked reads as unknown rather than up to date |
| `test_diagnostics.py` | That the key list handed to Home Assistant's redaction helper covers the secrets EdgeOS puts in its configuration tree, that the useful parts survive, and that redaction does not damage the live data |

## Writing a suite

The suites are plain scripts rather than a test framework, because the point is to run them anywhere with
no dependency beyond the standard library. The shape is:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hastub  # noqa: E402

hastub.install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

`hastub.install()` must run before anything under `custom_components` is imported. After it, import the
real modules and assert against them with the local `check(label, actual, expected)` helper, which records
failures and prints one line per assertion.

If a module the integration imports is missing from the stub, add it to `hastub.py` rather than stubbing it
inside a single suite - a per-suite stub silently shadows the shared one and the suites then disagree about
what Home Assistant looks like.
