# device_package_lan_demo

**English** | [中文](README_zh.md)

An external device package for Uni-Lab-OS that demonstrates a **LAN cross-device closed loop**: a
central hub (host) and a sub device (slave) run as separate processes and demonstrate the full loop
of cross-device `@subscribe` + remote control via `call_device_action` (ros action).

## Devices

| Device class           | Class                | Role                                                                              |
| ---------------------- | -------------------- | -------------------------------------------------------------------------------- |
| `hub_node_demo`        | `HubNodeDemo`        | Hub: cross-device subscribes the sub's `counter`; after N hits terminates the sub via ros action |
| `status_reporter_demo` | `StatusReporterDemo` | Sub: a self-growing `counter` published periodically; current round can be terminated remotely |

## Prerequisites

```bash
mamba activate unilab          # ROS 2 (humble) + unilabos environment
cd <repo-root>                 # run all commands from the Uni-Lab-OS repo root
```

> **Credentials are mandatory.** `unilabos.app.main` exits immediately if `--ak` / `--sk` are not
> provided (it needs a lab on the cloud). Reuse the AK/SK/addr from your IDE "test" run
> configuration (or your own account at <https://leap-lab.bohrium.com>). `--upload_registry` is the
> only optional cloud flag (it pushes the registry; drop it for a faster start). There is **no**
> fully offline mode — `--ak/--sk/--addr` must always be present.

---

## How it works

```
sub_reporter: counter self-grows (4/s) -> @topic_config publishes /devices/sub_reporter/counter
        │  (1) cross-device @subscribe
        ▼
hub.on_sub_counter: accumulates the number of received messages
        │  (2) if-check: from the first hit, once it reaches terminate_after (default 20)
        ▼
call_device_action(sub_reporter, "stop_counting")   (3) terminate the sub's current round via ros action
        │
        ▼
sub counter resets to 0 (pause cycle_pause s) -> hub detects "round reset" -> starts the next round, repeat
```

### Framework features showcased

- **Cross-device `@subscribe`**: `@subscribe(device_id="sub_reporter", status_name="counter")`
  subscribes to *another* device's status topic. `@subscribe` is cross-device only — to read
  your own status just use a getter.
- **Auto `msg_type` + retry until established**: no `msg_type` is given. The framework retries
  type resolution on an interval (default 10s, **no attempt cap, until subscribed**), so the hub
  picks up the type from the ROS graph as soon as the sub comes online — **independent of
  host/slave start order**. `retry_interval` only customizes the interval.
  > Note: when relying on auto-detection, do NOT annotate the callback's first parameter with a
  > Python built-in type (e.g. `value: int`), or it will be mistaken for `msg_type`.
- **Values go through msg convert**: the callback value is always converted by
  `convert_from_ros_msg` — `std_msgs` basics become native values (`Int32 -> int`,
  `String -> str`), composite messages become dicts.
- **`trigger_when_change`**: `on_sub_state` subscribes the sub's `state`, which is published
  continuously but only fires the callback on a real `running <-> paused` transition.
- **`call_device_action` (cross-device call)**:
  `self._ros_node.call_device_action(device, action, kwargs_dict)` takes a **dict** (the framework
  serializes internally), auto-detects whether to use a native ros action or the serial command
  channel, and returns a parsed dict/native value. Remote failures raise `DeviceActionError`.

---

## Launch tutorial (host first, then slave; two processes on one machine is fine)

Both processes scan the same package (`--devices ./device_package_lan_demo/lan_demo`) and use
`--external_devices_only`; only the graph file and `--is_slave` differ.
**Always start the host first, then the slave** (the slave waits for the host service by default).

**Step 1 — start the host (hub):**

```bash
python -m unilabos.app.main \
  --devices ./device_package_lan_demo/lan_demo \
  --external_devices_only \
  --ak <YOUR_AK> --sk <YOUR_SK> --addr test --upload_registry \
  --disable_browser --port 8101 \
  -g ./device_package_lan_demo/examples/host.json
```

**Step 2 — in another terminal, start the slave (sub):**

```bash
python -m unilabos.app.main \
  --devices ./device_package_lan_demo/lan_demo \
  --external_devices_only --is_slave \
  --ak <YOUR_AK> --sk <YOUR_SK> --addr test --upload_registry \
  --disable_browser --port 8102 \
  -g ./device_package_lan_demo/examples/slave.json
```

> PyCharm: duplicate the existing "test" run configuration (Module = `unilabos.app.main`, keep its
> AK/SK/addr env), make host/slave copies, and set Parameters to the above.
> For a real cross-machine LAN, put the two configs on two machines on the same LAN with a matching
> `ROS_DOMAIN_ID`.

### Expected output (verified)

This tutorial has been run end-to-end; the slave log cycles like this:

```
[REPORT][sub] round 1 begins: counter grows from 0
[REPORT][sub] stop_counting: round 1 terminated at 25, next round in 5.0s
[REPORT][sub] round 2 begins: counter grows from 0
[REPORT][sub] stop_counting: round 2 terminated at 19, next round in 5.0s
... repeats indefinitely ...
```

Each `stop_counting` is triggered remotely by the hub once it has accumulated 20 received
`counter` messages — proving cross-device subscribe, the ros-action remote call, and round-reset
detection all work. You can also kill the slave and restart it: the host re-discovers it (DDS
re-discovery) and re-subscribes automatically, no host restart needed.

### Manual cross-device call (optional)

The hub action `hub_node.call_peer(target_device, function_name, function_args)`:
- `function_args` is a **JSON string** from the UI; the action `json.loads` it into a dict before
  passing it to `call_device_action`.
- e.g. call the sub's generic echo: `function_name="echo"`, `function_args={"message": "hello"}`.

### Stopping

Stop each process with `Ctrl+C` (or kill the two PIDs).

---

## Registry check (validate the package without launching)

```bash
cd device_package_lan_demo
unilab --check_mode --devices ./lan_demo --external_devices_only
```

## Troubleshooting

- Process exits right after start with "请前往 ... 注册实验室" / "register a lab": `--ak/--sk` were
  missing or invalid. They are mandatory (see Prerequisites).
- `[MessageProcessor] server registration code 200, previous process may not have exited`,
  reconnecting repeatedly: a stale cloud session for the same account. It only affects cloud sync,
  **not** the local ROS closed loop.
- Slave hangs at startup: make sure the **host is started first** (the slave waits for the host
  service). Add `--slave_no_host` to skip that wait.
- Port already in use: give the host and slave **different** `--port` values.

## Directory structure

```
device_package_lan_demo/
├── README.md                     # English (this file)
├── README_zh.md                  # 中文
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .github/workflows/check_registry.yml
├── examples/                     # cross-device host/slave graphs
│   ├── host.json                 # hub (host)
│   └── slave.json                # sub (slave, --is_slave)
└── lan_demo/                     # python package scanned by --devices
    ├── __init__.py
    ├── hub_node.py               # HubNodeDemo (hub)
    └── status_reporter.py        # StatusReporterDemo (sub)
```
