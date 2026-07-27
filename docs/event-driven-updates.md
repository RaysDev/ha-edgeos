# Event driven updates

Where the integration reacts to the router pushing data, where it still polls, and why.

## What the router can push

The statistics WebSocket (`wss://<router>/ws/stats`) accepts a subscription list. Each subscribed
topic is then streamed without being asked for again.

| Topic | Content | Used |
| ----- | ------- | ---- |
| `system-stats` | CPU, memory, uptime | yes |
| `interfaces` | per interface link state, speed, duplex, MAC, addresses, traffic counters | yes |
| `export` | Traffic Analysis (DPI) per device | yes |
| `discover` | Ubiquiti device discovery | yes |
| `config-change` | a configuration commit started / ended | **added** |
| `num-routes` | connected / static / total route counts | no, not an existing entity |
| `users` | logged in sessions | no, not an existing entity |
| `fw-stats` | per rule firewall counters, one subscription per chain | no, see below |
| `nat-stats`, `pf-stats` | NAT and port forwarding counters | no, not an existing feature |
| `log-feed` | `/var/log/messages` tail | no |

## The gap that was closed

Everything derived from the router's *configuration* — firewall rules, interface settings, DHCP
static mappings, the logged in user's permission level — was only ever read by polling
`/api/edge/get.json` on `update_api_interval`, which defaults to 60 seconds.

That produced a visible bug on the firewall rule switches. Toggling one:

1. wrote the change to the router successfully, then
2. called `async_request_refresh()`, which does **not** re-read the configuration, then
3. was overwritten within a second by the next WebSocket message, because every message re-runs the
   data processors against the still cached configuration,

so the switch snapped back to its old position and stayed there for up to a minute before
correcting itself. A change made in the router's own web UI was invisible for just as long.

### `config-change`

The router announces every commit, from any source — this integration, the web UI, or the CLI:

```json
{"config-change": {"commit": "started"}}
{"config-change": {"commit": "ended"}}
```

On `ended`, the integration re-reads the configuration. Config derived entities now update within
about a second of any change, including changes made outside Home Assistant. New firewall rules and
new interfaces are also discovered that quickly, rather than on the next poll.

The refresh is deliberately narrow: it re-reads `get.json` only, not the four statistics endpoints,
because a commit does not change those and re-fetching them would add avoidable load.

### Requesting a refresh after writing

The commit event is the primary trigger, but it arrives over the WebSocket. If the WebSocket happens
to be down, a change made from Home Assistant would otherwise not be visible until the next poll,
so writes also request a refresh directly.

### Not bouncing back

An immediate refresh still takes a round trip, and in the meantime the processors keep re-reading
the cached configuration. So a state written from Home Assistant is now held as *pending* and
survives those re-reads until either the router confirms it, or `PENDING_STATE_TIMEOUT` (15 seconds)
elapses — at which point the real state is reported again, with a warning. A write the router
silently rejects is therefore visible rather than hidden forever.

### Polling is unchanged

None of this replaced the periodic poll. `update_api_interval` still re-reads everything on
schedule, so a missed or unsupported `config-change` event costs latency, not correctness.

## Firewall rule lifecycle

A rule is identified by its rule-set and its number, `WAN_IN:20`, with IPv6 rule-sets prefixed
because they live in a separate section of the configuration and may reuse a name.

| Change on the router | Effect |
| -------------------- | ------ |
| Rule added | Discovered on the next configuration read, so about a second after the commit. An entity is created on its rule-set's device. |
| Rule's description edited | Same identity, so the existing entity is renamed rather than replaced. |
| Rule's action, protocol or ports edited | Same identity, so the existing entity updates. Nothing is created or destroyed. |
| Rule enabled or disabled | The `Enabled` entity updates. |
| Rule renumbered, `20` to `25` | Its identity changed, so this is a removal plus an addition. |
| Rule-set renamed | A new device, with every rule re-added onto it. The old device is deleted once the removal is confirmed. |
| Rule deleted | Its entity stops reporting immediately. The rule-set's device stays, unless that was its last rule. |

### Removal

Three things have to be cleaned up, and each used to be left behind:

1. The processor drops the rule, so it stops reporting a state.
2. The discovery bookkeeping forgets it, so a rule that comes back is discovered again rather than
   being ignored as already known.
3. The device and its entities are removed from the registries.

The third step is driven by the **device registry**, not by what was discovered during this session.
That matters because a rule deleted while Home Assistant was not running would otherwise never be
noticed — it was never discovered this time round, so there would be nothing to compare against, and
its device would sit there permanently unavailable.

### Why removal waits

Deleting a device destroys the customisations attached to it — renamed entities, area assignments,
icons — and that cannot be undone. A single unusual configuration read must therefore not be enough
to trigger it, so a rule has to stay absent for `REMOVED_ITEM_GRACE_PERIOD` (2 minutes) before its
device is deleted. A rule that reappears within that window clears the timer and is never touched.

Two further guards apply. Removal is only ever evaluated after a genuine read of the configuration,
never against the cached copy that the WebSocket messages are processed against. And if no
configuration has been read at all — at startup, or while the router is unreachable — the check
returns immediately, because an empty rule list at that point means "not known yet", not "all rules
were deleted".

The per-rule `Monitored` preference is deliberately kept in storage after a removal, so that a rule
which comes back returns with the setting it had.

### Not applied to interfaces or devices

The same machinery is not used for the other device types, on purpose:

- **Devices** come and go with DHCP leases. A device tracker is supposed to survive its device going
  away — that is what reports it as away — so removing entities on a lease expiry would be wrong.
- **Interfaces** are partly discovered from the WebSocket stream rather than the configuration.
  Dynamic interfaces such as `pppoe0` and `vtun0` never appear in the configuration section at all,
  so pruning to what the configuration lists would delete them. Removing an interface from a router
  is also rare enough that the payoff does not justify the risk.

## What was deliberately not converted

### Firewall rule counters (`fw-stats`)

There is a raw WebSocket subscription that streams per rule packet and byte counters, and it is
richer than the REST endpoint — it includes the action and description per rule. It was not used:

- It needs **one subscription per chain**, with a `chain` parameter, so the subscription list has to
  be rebuilt whenever chains are added or removed.
- The router shells out to `iptables` per chain per interval to produce it. On an ER-X, streaming
  every chain continuously is a real and permanent CPU cost, against a REST endpoint that returns
  every chain in a single call once a minute.
- Two sources writing the same counter will disagree about ordering. A REST response read slightly
  earlier but applied slightly later would move a counter backwards, which Home Assistant's
  `TOTAL_INCREASING` handling interprets as a meter reset and records as a spurious spike.

These are statistics rather than state, so a one minute resolution is not the problem the switches
were. If it is wanted later, the sane design is to subscribe only to chains that contain a rule the
user marked as monitored — that keeps the router cost proportional to what was actually asked for —
and to ignore the REST counters entirely while the stream is delivering.

### DHCP leases, system information

`dhcp_leases`, `dhcp_stats` and `sys_info` have no WebSocket equivalent. New DHCP clients therefore
still appear within one poll interval. Devices with a static mapping in the configuration are now
picked up immediately, since those come from the configuration.

### Interface link state

Already event driven. `interface.up` and `l1up` come from the `interfaces` stream, so enabling or
disabling an interface is reflected in a second or two without any of the above. Only the
configuration side of an interface benefits from `config-change`.

### Entity refresh rate

Entities are refreshed from the coordinator on `update_entities_interval`, one second by default.
Pushing an update per incoming WebSocket message instead would mean re-evaluating every entity
several times a second for no visible benefit, so the one second cycle is kept as the batching
point. It is also what debounces a burst of commits down to a single configuration read.
