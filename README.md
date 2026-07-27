# EdgeOS

Provides an integration between EdgeOS (Ubiquiti) routers and Home Assistant.

A fork of [elad-bar/ha-edgeos](https://github.com/elad-bar/ha-edgeos), which is no longer actively
developed. This version restores support for EdgeOS 3.x, adds firewall rule control, and reworks how the
integration connects to the router and presents what it finds.

[Changelog](https://github.com/blchinezu/ha-edgeos/blob/master/CHANGELOG.md)

## How to

#### Requirements

- EdgeRouter running EdgeOS 2.0 or later, including 3.x
- A router user with `operator` level access or higher
- Traffic Analysis set to 'Enabled' - both `dpi` and `export` under `system/traffic-analysis`
- An `admin` user to enable or disable interfaces and firewall rules. An `operator` sees them as
  read-only sensors instead of switches

#### Installation via HACS

This is not in the default HACS store, so add it as a custom repository first:

- HACS -> three-dot menu -> Custom repositories
- Repository `https://github.com/blchinezu/ha-edgeos`, type `Integration`
- Then look for "Ubiquiti EdgeOS Routers", install it, and restart Home Assistant
- Settings -> Devices & Services -> Add Integration

#### Setup

To add the integration use Configuration -> Integrations -> Add `EdgeOS`.
The integration supports **multiple** EdgeOS devices.

| Fields name | Type    | Required | Default | Description                                                                                     |
| ----------- | ------- | -------- | ------- | ----------------------------------------------------------------------------------------------- |
| Name        | Textbox | +        | EdgeOS  | Name of this router in Home Assistant                                                           |
| Host        | Textbox | +        | -       | Hostname or IP address of the EdgeOS device, may include a port (HOST:PORT), default port is 443 |
| Username    | Textbox | +        | -       | A user with `operator` level access or higher. A dedicated user makes issues easier to identify |
| Password    | Textbox | +        | -       |                                                                                                 |

###### EdgeOS Device validation errors

| Errors                                                                             |
| ---------------------------------------------------------------------------------- |
| Cannot reach device (404)                                                          |
| Invalid credentials (403)                                                          |
| General authentication error (when failed to get valid response from device)       |
| Could not retrieve device data from EdgeOS Router                                  |
| Export (traffic-analysis) configuration is disabled, please enable                 |
| Deep Packet Inspection (traffic-analysis) configuration is disabled, please enable |
| Unsupported firmware version                                                       |

###### Encryption key got corrupted

If a persistent notification popped up with the following message:

```
Encryption key got corrupted, please remove the integration and re-add it
```

It means that the encryption key was modified from outside the code.
Please remove the integration and re-add it to make it work again.

#### Options

_Configuration -> Integrations -> {Integration} -> Options_ <br />

The same four fields as the initial setup. Changing the host, username or password re-validates against
the router before anything is saved.

The polling intervals and the unit used for traffic are entities on the router's device rather than
options - see [System](#system) below.

## Components

### System

Entities on the router itself.

| Entity Name                              | Type   | Description                                                            | Additional information                       |
| ---------------------------------------- | ------ | ---------------------------------------------------------------------- | -------------------------------------------- |
| {Router Name} CPU Usage                  | Sensor | Current CPU usage                                                      |                                              |
| {Router Name} RAM Usage                  | Sensor | Current memory usage                                                   |                                              |
| {Router Name} Last Restart               | Sensor | When the router last restarted                                         | Derived from its uptime                      |
| {Router Name} Unknown Devices            | Sensor | Number of devices leased by the DHCP server without a static mapping   | Attributes hold their hostnames and IPs      |
| {Router Name} Firmware Upgrade           | Update | The firmware the router is running, and whether a newer one is offered | Reports only, it does not install            |
| {Router Name} Unit                       | Select | Unit used by every traffic sensor - bytes, kilobytes or megabytes      | Changing it re-creates the traffic sensors   |
| {Router Name} Consider Away Interval     | Number | How long without traffic before a tracked device counts as away        | Seconds                                      |
| {Router Name} Update Entities Interval   | Number | How often entities are refreshed from what the integration holds       | Seconds, minimum 1, reloads the integration  |
| {Router Name} Update API Interval        | Number | How often the router is polled for data it does not push               | Seconds, minimum 1, reloads the integration  |
| {Router Name} Log Incoming Messages      | Switch | Logs incoming WebSocket messages, for debugging                        |                                              |

### Per device

Every device configured as a DHCP static mapping on the router gets a monitoring toggle on one shared
device, `{Router Name} Device Monitoring`. A network with fifty static mappings therefore adds one device,
not fifty.

| Entity Name                              | Type   | Description                                                       |
| ---------------------------------------- | ------ | ------------------------------------------------------------------ |
| {Router Name} Device Monitoring {Device} | Switch | Sets whether to monitor that device and create the entities below |

A device only gets a device of its own in Home Assistant once its toggle is on. Turn the toggle off and
the entities below go, and the now empty device is deleted two minutes later.

| Entity Name                                  | Type           | Description                                                                     | Additional information      |
| -------------------------------------------- | -------------- | ------------------------------------------------------------------------------- | --------------------------- |
| {Router Name} {Device Name} Received Rate    | Sensor         | Received Rate per second                                                        | Statistics: Measurement     |
| {Router Name} {Device Name} Received Traffic | Sensor         | Received total traffic                                                          | Statistics: Total Increment |
| {Router Name} {Device Name} Sent Rate        | Sensor         | Sent Rate per second                                                            | Statistics: Measurement     |
| {Router Name} {Device Name} Sent Traffic     | Sensor         | Sent total traffic                                                              | Statistics: Total Increment |
| {Router Name} {Device Name}                  | Device Tracker | Indication whether the device is or was connected over the configured timeframe |                             |

A toggle is named after the device's hostname, tidied the same way a firewall rule description is:
separators become spaces, and a word is capitalised only when it is entirely lower case, so `iPhone-Gabi`
reads `iPhone Gabi` and `NAS_Main` reads `NAS Main`.

### Per interface

Interfaces keep their own `Monitored` switch on the interface itself. There are only a handful of them,
so there is nothing to consolidate.

| Entity Name                                             | Type          | Description                                                                  | Additional information                      |
| ------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------- | ------------------------------------------- |
| {Router Name} {Interface Name} Status                   | Switch        | Sets whether the interface is active or not                                  | Available only if user level is `admin`     |
| {Router Name} {Interface Name} Status                   | Binary Sensor | Indicates whether the interface is active or not                             | Available only if user level is not `admin` |
| {Router Name} {Interface Name} Connected                | Binary Sensor | Indicates whether the interface's port is connected or not                   |                                             |
| {Router Name} {Interface Name} Monitored                | Switch        | Sets whether to monitor interface and create all the components below or not |                                             |
| {Router Name} {Interface Name} Received Rate            | Sensor        | Received Rate per second                                                     | Statistics: Measurement                     |
| {Router Name} {Interface Name} Received Traffic         | Sensor        | Received total traffic                                                       | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Received Dropped Packets | Sensor        | Received packets lost                                                        | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Received Errors          | Sensor        | Received errors                                                              | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Received Packets         | Sensor        | Received packets                                                             | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Sent Rate                | Sensor        | Sent Rate per second                                                         | Statistics: Measurement                     |
| {Router Name} {Interface Name} Sent Traffic             | Sensor        | Sent total traffic                                                           | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Sent Dropped Packets     | Sensor        | Sent packets lost                                                            | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Sent Errors              | Sensor        | Sent errors                                                                  | Statistics: Total Increment                 |
| {Router Name} {Interface Name} Sent Packets             | Sensor        | Sent packets                                                                 | Statistics: Total Increment                 |

### Per firewall rule-set

Every firewall rule-set configured on the router is discovered automatically and exposed as one device,
named `{Router Name} Firewall {Rule-set}`. Each of its rules is a single entity on that device, so a
router with eighty rules produces a handful of devices rather than eighty.

IPv6 rule-sets live in a separate section of the EdgeOS configuration and may reuse an IPv4 rule-set
name, so they are their own device - `{Router Name} Firewall IPv6 {Rule-set}`.

| Entity Name                              | Type          | Description                                   | Additional information                      |
| ---------------------------------------- | ------------- | --------------------------------------------- | ------------------------------------------- |
| {Router Name} Firewall {Rule-set} {Rule} | Switch        | Enables or disables that rule on the router   | Available only if user level is `admin`     |
| {Router Name} Firewall {Rule-set} {Rule} | Binary Sensor | Indicates whether that rule is enabled or not | Available only if user level is not `admin` |

The rule's action, protocol, description, number, connection states, source, destination and the
rule-set's default action are exposed as attributes of the entity.

Toggling the switch adds or removes the rule's `disable` node through the EdgeOS configuration API, which
is the same thing the router's web UI does - the change is committed and saved, so it survives a reboot.

#### How a rule is named

A rule is named after its `description`, since that is the only human readable thing EdgeOS holds about
it. A description written as prose is used exactly as it was typed; one written in the usual
`block-kid-tablet` or `block_guest_tv` style has its separators turned into spaces and each word given an
initial capital - only where the word is entirely lower case, so `DNS`, `WAN`, `IPv6` and `iPhone`
survive.

| On the router      | In Home Assistant  |
| ------------------ | ------------------ |
| `block-kid-tablet` | Block Kid Tablet   |
| `block_guest_tv`   | Block Guest Tv     |
| `Allow DNS out`    | Allow DNS out      |
| no description     | rule 760           |

Renaming a rule on the router renames its entity within about a second. The entity is identified by its
rule-set and number rather than by its description, so renaming never creates a second entity or strands
the one you had.

Notes:

- Rules are listed alphabetically on the device, not in the order the router evaluates them. The rule
  number is available as an attribute.
- A rule-set removed from the router has its device and entities deleted, two minutes after it was last
  seen. A single rule removed from a rule-set that still exists takes only its own entity with it.

## Upgrading from 2.1.9

Two things change shape. Everything else keeps its entity id and its history.

**The firmware entity.** `binary_sensor.{router}_firmware_updates` is replaced by an `update` entity on
the same device, which shows the installed and available versions rather than just on or off. An
automation on the old entity needs repointing. The old entity is removed on upgrade rather than left
behind as permanently unavailable.

**Device monitoring.** The `Monitored` switches move onto a single `{Router Name} Device Monitoring`
device. The switches themselves keep their entity ids and history, so automations carry on working - but
the Home Assistant devices of anything you have not monitored are deleted, along with any rename you gave
one of them.

Entity ids of entities Home Assistant has already registered keep their old names, which will not match
the new naming. To regenerate them, remove and re-add the integration.

## Troubleshooting

### Debug logs

To set the log level of the component to DEBUG, please set it from the options of the component if
installed, otherwise, set it within configuration YAML of HA:

```yaml
logger:
  default: warning
  logs:
    custom_components.edgeos: debug
```

### Diagnostic file

In Settings -> Devices & services, look for the device, click on the 3 dots menu and download the
diagnostic file.

Session cookies and the credential-bearing parts of the router's configuration - user password hashes,
VPN keys, dynamic DNS passwords - are redacted before the file is written. Read it before sharing it
anyway, then attach it to an issue.

## Development

The integration can be exercised without Home Assistant or a router:

```
tests/run.sh
```

Thirteen offline suites run the real code under `custom_components/edgeos` against stubbed Home Assistant
modules and scripted fake routers. See [tests/README.md](tests/README.md).

`tools/probe_router.py` is a read-only probe that reports what a given router actually exposes - which
data endpoints answer, which WebSocket topics deliver, and where its configuration can be read from. It
issues no writes.
