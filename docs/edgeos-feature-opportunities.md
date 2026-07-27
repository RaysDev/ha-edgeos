# EdgeOS capabilities not yet covered by ha-edgeos

Research notes on what else the EdgeOS API exposes that could be surfaced in, or controlled from,
Home Assistant. Nothing here is implemented — this is a shortlist for deciding what to build next.

## Sources

- [Ubiquiti Community Wiki — EdgeOS API](https://ubntwiki.com/products/software/edgeos/api)
- [Matthew1471/EdgeOS-API](https://github.com/Matthew1471/EdgeOS-API) — the most complete reverse-engineered
  reference: every REST endpoint, every WebSocket subscription, with request/response schemas and examples
- [andrewstuart/edgeos-rest](https://github.com/andrewstuart/edgeos-rest) — Go structs generated from a real
  `get.json` dump, useful for confirming how the configuration tree is actually serialised
- [brontide/aioedgeos](https://github.com/brontide/aioedgeos) — async Python client
- The `custom_components/edgeos` source in this repository, to establish what is already covered

## What the integration already does today

| Scope         | Covered                                                                                                                             |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| System        | CPU %, RAM %, last restart, unknown (leased) device count, firmware-update indication, WS message logging toggle, unit/interval config |
| Per interface | Admin/link status (switch or binary sensor), monitored toggle, rx/tx rate, traffic, packets, errors, dropped                          |
| Per device    | rx/tx rate and traffic, device tracker, monitored toggle                                                                              |
| Per firewall rule | Enable/disable, matched packets and traffic *(added in this branch)*                                                             |

Data the integration **already fetches on every poll but never surfaces**: the full `dhcp_stats` pool
breakdown, `sys_info.unms`, the interface address list, the per-application split inside the DPI `export`
stream, and the `offload` / `traffic-analysis` configuration flags.

## Scoring

- **Useful** — confidence that this is worth having in Home Assistant: High / Medium / Low
- **Effort** — implementation cost: Trivial / Easy / Medium / Hard
- **Path** — confidence that the implementation path is clear and documented: Certain / High / Medium / Speculative

## Summary

| #   | Feature                                       | Kind    | Useful | Effort  | Path      | Recommendation      |
| --- | --------------------------------------------- | ------- | ------ | ------- | --------- | ------------------- |
| 1   | WAN / interface IP address sensor             | Read    | High   | Trivial | Certain   | **Do first**        |
| 2   | DHCP pool utilisation sensors                 | Read    | Medium | Trivial | Certain   | **Do first**        |
| 3   | Port forwarding rules enable/disable          | Control | High   | Easy    | Certain   | **Do first**        |
| 4   | Logged-in users sensor                        | Read    | High   | Easy    | High      | **Do**              |
| 5   | Reboot button                                 | Control | High   | Trivial | Certain   | **Do**              |
| 6   | Check-for-firmware-updates button             | Control | Medium | Trivial | Certain   | **Do**              |
| 7   | `config-change` driven refresh                | Internal| High   | Easy    | High      | **Do**              |
| 8   | NAT rules enable/disable                      | Control | Medium | Easy    | High      | Do                  |
| 9   | Route count sensors                           | Read    | Medium | Easy    | Certain   | Do                  |
| 10  | UNMS/UISP daemon binary sensor                | Read    | Low    | Trivial | Certain   | Do (cheap)          |
| 11  | DPI per-application breakdown                 | Read    | High   | Medium  | High      | Do, with care       |
| 12  | Traffic-analysis (DPI/export) toggles         | Control | Medium | Easy    | High      | Do, admin-gated     |
| 13  | DHCP renew/release per interface              | Control | Medium | Easy    | Certain   | Consider            |
| 14  | Port-forward / NAT statistics                 | Read    | Medium | Medium  | High      | Consider            |
| 15  | Scoped config fetch (`getcfg.json`)           | Internal| Medium | Easy    | High      | Consider            |
| 16  | Configuration backup service                  | Control | Medium | Medium  | High      | Consider            |
| 17  | Clear traffic analysis button                 | Control | Low    | Trivial | Certain   | Consider            |
| 18  | Service toggles (SSH/GUI/UPnP/UNMS)           | Control | Medium | Easy    | High      | Risky — opt-in only |
| 19  | Hardware offload toggles                      | Control | Low    | Easy    | High      | Risky               |
| 20  | Ping / traceroute / bandwidth test services   | Control | Medium | Hard    | Medium    | Later               |
| 21  | Log feed                                      | Read    | Medium | Medium  | High      | Later, filtered     |
| 22  | Firmware upgrade (`update` entity)            | Control | Medium | Hard    | Medium    | Later               |
| 23  | Discovered Ubiquiti neighbours                | Read    | Low    | Medium  | High      | Low priority        |
| 24  | Shutdown / factory reset / config restore     | Control | Low    | Easy    | Certain   | **Don't**           |
| 25  | Raw CLI passthrough service                   | Control | Medium | Hard    | Medium    | **Don't**           |
| 26  | Packet capture                                | Read    | Low    | Hard    | High      | **Don't**           |
| 27  | LLDP neighbours, GPON/ONU/PON                 | Read    | Low    | Medium  | Speculative| **Don't**          |

---

## Quick wins — the data is already in memory

### 1. WAN / interface IP address sensor

The `interfaces` WebSocket stream already delivers each interface's address list, and
`InterfaceProcessor._update_interface_stats` already stores it as `interface.address`. Today it only
appears as an attribute of the interface status entity.

- **How**: a new `INTERFACE_ADDRESS` sensor per interface reading `interface.address[0]`. No new API calls.
- **Pros**: "what is my public IP" is one of the most common router-integration asks — dynamic DNS updates,
  alerting on WAN IP change, conditioning automations on being on a specific ISP link. Zero extra polling cost.
- **Cons**: an interface can hold multiple addresses; needs a sensible choice (first non-link-local) with the
  full list kept as an attribute. On PPPoE the address lives on the `pppoe0` dynamic interface, not `eth0`.
- **Useful: High · Effort: Trivial · Path: Certain** — recommended as the single highest value-per-line change.

### 2. DHCP pool utilisation sensors

`dhcp_stats` is already fetched every poll. `SystemProcessor` reads only the `leased` field of each subnet and
sums it into the "unknown devices" count; `pool-size` and `available` are discarded.

- **How**: expose per shared-network sensors for pool size, leased and available, plus a utilisation percentage.
- **Pros**: free — no new requests. Genuinely useful alerting ("DHCP pool 90% full").
- **Cons**: creates a new device type (or attaches to the system device) for a fairly niche metric on
  small home networks with one pool.
- **Useful: Medium · Effort: Trivial · Path: Certain**

### 3. Port forwarding rules enable/disable

Structurally identical to the firewall rules added in this branch: `port-forward { rule N { disable } }`,
toggled with the same `set.json` / `delete.json` pair.

- **How**: reuse `RestAPI._set_disable_node` with `{"port-forward": {"rule": {"N": {"disable": null}}}}`, and a
  processor that mirrors `FirewallProcessor`. Counters available from the `pf-stats` WebSocket subscription.
- **Pros**: arguably a more common automation target than firewall rules — temporarily opening a game server
  or a camera port, closing everything while away. The pattern is already proven in this codebase.
- **Cons**: port-forward rules are a flat list, not grouped into rule-sets, so the identifier scheme is simpler
  but the descriptions are often empty, making entity names opaque without the rule's port in the name.
- **Useful: High · Effort: Easy · Path: Certain**

### 10. UNMS/UISP daemon binary sensor

`sys_info.unms.daemon` is already fetched and reports `Running` / `Not running`.

- **Pros**: free; relevant for anyone managing the router through UISP.
- **Cons**: meaningless for users not running UISP — should probably be created only when the service exists.
- **Useful: Low · Effort: Trivial · Path: Certain**

---

## Monitoring

### 4. Logged-in users sensor

WebSocket subscription `users` returns local sessions with `tty` (`Web`, `pts/0`, VPN), `host`, `idle` and
`uptime`.

- **How**: add `users` to the WS subscription list, a count sensor plus the session list as attributes.
- **Pros**: a real security signal — "someone just logged into the router" is an excellent notification trigger,
  and it also catches an unexpected SSH session. This is not obtainable any other way from HA.
- **Cons**: the integration's own session shows up as a `Web` user, so the count has a permanent baseline of at
  least one and automations must account for that.
- **Useful: High · Effort: Easy · Path: High** — the payload shape is documented with examples.

### 9. Route count sensors

WebSocket `num-routes` gives `connected` / `static` / `total`; REST `data=routes` gives the full table.

- **Pros**: trivial to add, meaningful for anyone running OSPF/BGP or multiple VPN tunnels — a dropping route
  count is a good tunnel-down signal.
- **Cons**: on a typical home router this is a constant number and pure noise.
- **Useful: Medium · Effort: Easy · Path: Certain**

### 11. DPI / Traffic Analysis per-application breakdown

This is the most under-used data the integration already receives. `WebSockets._handle_export` iterates the
per-service breakdown and **sums it all into a single rx/tx total per device**, discarding which applications
the traffic belonged to.

- **How**: keep the per-service dictionary alongside the totals; expose a "top applications" sensor per device
  (state = top app name, attributes = the ranked breakdown) and/or a router-wide equivalent.
- **Pros**: DPI is EdgeOS's headline feature and no other HA integration surfaces it. Enables "how much Netflix
  did this device use today", per-application alerting, and much richer dashboards.
- **Cons**: real entity-explosion risk if modelled as one sensor per application per device — a busy network has
  hundreds of combinations. Needs a top-N attribute-based design rather than entity-per-app. DPI must be enabled
  on the router, and its category names are Ubiquiti-specific and unstable across firmware.
- **Useful: High · Effort: Medium · Path: High** — the data already arrives; the difficulty is modelling, not access.

### 14. Port forwarding and NAT statistics

Raw WebSocket feeds `pf-stats` (`rule pkts bytes`) and `nat-stats`
(`rule pkts type interface "description" [DISABLED]`).

- **Pros**: completes the picture alongside firewall statistics; `nat-stats` even reports the disabled state,
  which is a useful cross-check.
- **Cons**: these are raw console text feeds, not JSON — they need line parsing, and the sample output shows the
  feed repeating the same block multiple times per message, so deduplication is required. Raw subscriptions also
  need `sub_id` bookkeeping the current WebSocket manager does not have.
- **Useful: Medium · Effort: Medium · Path: High**

### 21. Log feed

`log-feed` is effectively `tail -f /var/log/messages` over the WebSocket.

- **Pros**: makes router events (DHCP, VPN connect/disconnect, firewall log rules) available to automations
  without a syslog server.
- **Cons**: extremely chatty. Feeding this into HA's state machine or recorder unfiltered is a bad idea. Would
  need to be fired as HA events with a configurable regex filter, and even then it is a recorder-pressure risk.
- **Useful: Medium · Effort: Medium · Path: High** — recommend firing events, never entities, and only opt-in.

### 23. Discovered Ubiquiti neighbours

The `discover` subscription is already consumed, but only to read the router's own product and firmware version.
It also lists other Ubiquiti devices found on the network.

- **Pros**: could auto-populate device trackers for UniFi APs, switches and other EdgeRouters.
- **Cons**: overlaps heavily with the existing DHCP-based device discovery and with the UniFi integration.
- **Useful: Low · Effort: Medium · Path: High**

---

## Control

### 5. Reboot button

`POST /api/edge/operation/reboot.json`.

- **Pros**: trivial to add; a genuinely useful recovery action for automations ("WAN down for 30 minutes → reboot").
- **Cons**: an accidental press takes the network down. Should be a `button` (not a switch), admin-gated, and
  ideally with `EntityCategory.CONFIG` so it does not appear on default dashboards.
- **Useful: High · Effort: Trivial · Path: Certain**

### 6. Check-for-firmware-updates button

`POST /api/edge/operation/refresh-fw-latest-status.json`. The existing firmware binary sensor only reflects the
router's cached `fw-latest` state, which the router refreshes on its own schedule.

- **Pros**: makes the existing firmware sensor trustworthy and current on demand.
- **Cons**: causes the router to reach out to Ubiquiti's servers; some users deliberately keep routers offline
  from vendor endpoints.
- **Useful: Medium · Effort: Trivial · Path: Certain**

### 8. NAT rules enable/disable

`service { nat { rule N { disable } } }`, again the same disable-node mechanism.

- **Pros**: same proven pattern; useful for masquerade/hairpin rules and for policy-based routing setups.
- **Cons**: NAT rule semantics are harder for a casual user to reason about than firewall rules, so the risk of
  someone breaking their own internet from a dashboard toggle is higher.
- **Useful: Medium · Effort: Easy · Path: High**

### 12. Traffic-analysis (DPI / export) toggles

`system { traffic-analysis { dpi ; export } }`. `SystemProcessor` already parses both flags into
`EdgeOSSystemData`, but they are only visible in diagnostics.

- **Pros**: nearly free to expose. DPI is CPU-expensive on small hardware like the ER-X, so being able to turn it
  off automatically (for example during a large transfer) is a real use case.
- **Cons**: turning `export` off blinds the integration's own per-device traffic sensors — the entity would be
  quietly sabotaging the rest of the integration. Needs a clear warning in the entity name or documentation.
- **Useful: Medium · Effort: Easy · Path: High**

### 13. DHCP renew/release per interface

`POST /api/edge/operation/renew-dhcp.json` and `release-dhcp.json`, with `{"interface": "eth0"}`.

- **Pros**: a targeted recovery action for a stuck WAN lease, cheaper than a full reboot.
- **Cons**: only meaningful on DHCP-client interfaces; would need to be created selectively or it becomes a
  no-op button on every LAN port.
- **Useful: Medium · Effort: Easy · Path: Certain**

### 16. Configuration backup service

`GET /api/edge/config/save.json` returns a temporary path, then `GET /files/config/` downloads it once.

- **Pros**: scheduled, versioned router config backups driven by HA automations is a genuinely valuable feature
  and nothing else in the HA ecosystem does it for EdgeOS.
- **Cons**: **the configuration contains password hashes, PSKs and VPN keys.** Writing it into HA's config
  directory means those secrets land in HA backups and possibly in cloud backup targets. This needs an explicit
  opt-in and a documented warning. The download is also single-shot — the temp file is deleted after the first
  fetch, so error handling matters.
- **Useful: Medium · Effort: Medium · Path: High**

### 17. Clear traffic analysis button

`POST /api/edge/operation/clear-traffic-analysis.json`.

- **Pros**: trivial; gives a way to reset DPI counters on a schedule (for example monthly).
- **Cons**: destroys history that the integration's own `TOTAL_INCREASING` sensors depend on, causing a counter
  reset that HA statistics will interpret as a meter reset.
- **Useful: Low · Effort: Trivial · Path: Certain**

### 18. Service toggles — SSH, web GUI, UPnP, UNMS, DNS forwarding

All live under `service { ... }` with the same disable-node pattern.

- **Pros**: UPnP on/off is a legitimate and commonly wanted security control. SSH on/off likewise.
- **Cons**: **disabling the web GUI locks the integration itself out of the router**, with no way back except the
  console. This is a genuine footgun and the reason to either exclude the GUI service specifically or hide the
  whole group behind an explicit opt-in option.
- **Useful: Medium · Effort: Easy · Path: High**

### 19. Hardware offload toggles

`system { offload { hwnat ; ipsec } }` — already parsed into `EdgeOSSystemData`.

- **Pros**: cheap to expose.
- **Cons**: offload changes only take effect after a reboot, so a switch would report a state that does not match
  reality until the router restarts — confusing and arguably worse than not having it. Turning hwnat off also
  tanks throughput on an ER-X.
- **Useful: Low · Effort: Easy · Path: High** — the honest recommendation is a read-only binary sensor, not a switch.

### 20. Ping / traceroute / bandwidth test services

WebSocket subscriptions `ping-feed`, `traceroute-feed` and `bwtest-feed` (the latter runs `iperf`).

- **Pros**: a ping sourced *from the router* measures the WAN edge, which is meaningfully different from HA's own
  ping integration running behind the router. `bwtest-feed` could give scheduled throughput measurements.
- **Cons**: these are streaming raw-text subscriptions with per-request parameters and lifecycle (subscribe, read
  until finished, unsubscribe) that the current WebSocket manager is not built for — it opens one connection with
  a fixed subscription set. Results arrive as console text needing parsing. `bwtest` needs an iperf peer.
- **Useful: Medium · Effort: Hard · Path: Medium**

### 22. Firmware upgrade as an HA `update` entity

`POST /api/edge/upgrade.json` as `multipart/form-data` with the firmware `.tar` in a `qqfile` field, followed by
a reboot. `sys_info.fw-latest` already provides the version, download URL and MD5.

- **Pros**: turns the existing firmware binary sensor into a proper `update` entity with a working install button,
  which is the idiomatic HA representation.
- **Cons**: HA would have to download a ~100 MB firmware image from Ubiquiti and re-upload it to the router,
  holding it in memory or on disk. A failed or interrupted flash can brick the device. MD5 verification is
  essential. This is the highest-consequence operation in the whole API.
- **Useful: Medium · Effort: Hard · Path: Medium** — worth doing eventually, but only with careful verification.

---

## Internal improvements

### 7. Use `config-change` to trigger an immediate refresh

The `config-change` subscription emits `commit: started` / `commit: ended` whenever the configuration changes,
from any source — the web UI, SSH, or the integration itself.

- **Pros**: today, toggling a firewall rule (or an interface) updates the entity only on the next API poll, up to
  `Update API Interval` seconds later, and a change made in the router's own web UI is invisible for just as long.
  Subscribing to `config-change` and re-reading `get.json` on `commit: ended` makes every config-derived entity
  update effectively instantly, and would fire an event usable for router-config-change alerting.
- **Cons**: needs debouncing — a batch of CLI changes emits many commits.
- **Useful: High · Effort: Easy · Path: High** — the best correctness-per-effort item on this list.

### 15. Scoped configuration fetches with `getcfg.json`

`GET /api/edge/getcfg.json?node[]=firewall` returns only the requested subtree, rather than `get.json` pulling the
entire configuration on every poll.

- **Pros**: less work for the router (relevant on an ER-X, where the GUI backend is a Python process on a modest
  CPU) and less JSON to parse each cycle.
- **Cons**: the response format differs from `get.json` — it is wrapped in `GETCFG` with `children` / `defs` /
  `tags` rather than being a plain configuration subtree, so processors would need a second parser. Only worth it
  if polling frequency increases.
- **Useful: Medium · Effort: Easy · Path: High**

---

## Not recommended

### 24. Shutdown, factory reset, configuration restore

`operation/shutdown.json`, `operation/reset-default-config.json`, and config restore all exist and are easy to call.

They are irreversible-by-dashboard-press. A shutdown requires physical access to recover from; a factory reset
destroys the configuration. There is no plausible home-automation use case that justifies the blast radius.
**Recommendation: do not expose.**

### 25. Raw CLI passthrough (`wss://host/ws/cli`)

- **Pros**: would make anything the router can do reachable from HA.
- **Cons**: an arbitrary-command service callable from any automation or script is a serious privilege-escalation
  surface within HA, output is unstructured console text, and it invites configurations the integration cannot
  model. **Recommendation: do not expose.**

### 26. Packet capture (`packets-feed`)

`tcpdump` over a WebSocket. High volume, no sensible HA representation, and a privacy hazard.
**Recommendation: do not expose.**

### 27. LLDP neighbours, GPON / ONU / PON, NNI statistics

`lldp-detail`, `onu-list`, `pon-stats` and `nni-stats` are referenced by the web UI, but the reference
documentation notes that several are no longer implemented in `ubnt-util`, and the GPON/ONU/PON ones apply only to
OLT and EdgePoint hardware rather than EdgeRouters.
**Useful: Low · Path: Speculative — not worth pursuing without hardware to test against.**

---

## Suggested order

1. **WAN IP sensor** (#1) — highest value per line of code, uses data already held in memory.
2. **`config-change` refresh** (#7) — makes the firewall switches and everything else config-derived feel instant.
3. **Port forwarding rules** (#3) — the pattern is already built and proven by the firewall work.
4. **Logged-in users** (#4) and **reboot button** (#5) — small, self-contained, high value.
5. **DHCP pool sensors** (#2) and **route counts** (#9) — cheap fillers.
6. **DPI per-application breakdown** (#11) — the biggest feature on the list; design the entity model before coding.
