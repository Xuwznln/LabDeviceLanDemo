# LabDeviceLanDemo

**English** | [中文](README_zh.md)

A finite, runnable Uni-Lab-OS LAN demo. The same two drivers run on both
`hostlink` and `ros2`:

1. `status_reporter_demo` publishes `counter` and `state`;
2. `hub_node_demo` receives them through cross-device `@subscribe`;
3. after N updates, the hub calls the reporter's `stop_counting` action;
4. the hub exposes `demo_complete=true` only after the remote action succeeds.

There is no cloud inventory dependency and no AK/SK requirement. HTTP remains the local
microbackend data plane; the device-to-device transport is selected by `--backend`.

## Install from GitHub

Recent Uni-Lab-OS versions accept an ordinary GitHub repository URL and discover the actual
distribution name (`lan_demo`) after installation:

```bash
unilab package install https://github.com/Xuwznln/LabDeviceLanDemo --ref <commit-sha>
```

For development, clone this repository and run commands from its root.

## Devices

| Registry id | Role |
| --- | --- |
| `hub_node_demo` | subscribes to reporter status and invokes the remote action |
| `status_reporter_demo` | publishes a growing counter and implements `stop_counting` |

Both declare `supported_backends=["hostlink", "ros2"]` and use only the shared `DeviceNode`
contract. No driver calls ROS node APIs directly.

## Finite smoke test

The smoke command starts real host and slave processes, waits for a proof JSON, validates the
backend name and terminal state, then stops both processes. It never relies on an infinite log.

```bash
# No ROS installation required
python -m lan_demo.smoke --backend hostlink --timeout 30

# Run inside a ROS 2 Jazzy/Humble environment
python -m lan_demo.smoke --backend ros2 --timeout 45
```

Successful output has this shape:

```json
{
  "success": true,
  "backend": "hostlink",
  "received_count": 3,
  "remote_action": "stop_counting",
  "remote_result": {"success": true},
  "closed_loops": 1
}
```

CI installs this repository through the ordinary GitHub URL plus the exact commit SHA, changes
to a directory outside the checkout, and then runs the two commands above in one Jazzy job. A
scheduled run checks Uni-Lab-OS `dev` at 08:00 Beijing time each day and only repeats the full
smoke when that branch has a new SHA (failed SHAs are retried).

## Manual HostLink launch

Choose one HostLink TCP port (7302 below). The management HTTP ports are independent.

Host:

```bash
unilab --backend hostlink --skip_env_check \
  --devices ./lan_demo --external_devices_only \
  --hostlink_bind 0.0.0.0 --hostlink_port 7302 \
  --disable_browser --port 8101 \
  -g ./examples/host.json
```

Slave (replace the host address on a real LAN):

```bash
unilab --backend hostlink --skip_env_check \
  --devices ./lan_demo --external_devices_only --is_slave \
  --host_node_ip 192.168.1.10 --hostlink_port 7302 \
  --disable_browser --port 8102 \
  -g ./examples/slave.json
```

HostLink reconnects after disconnects. `--host_node_ip` may be an IP address or DNS name; it is
not the management HTTP address.

## Manual ROS2 launch

Use the same graph files and driver logic. Both processes must share `ROS_DOMAIN_ID`.

Host:

```bash
unilab --backend ros2 --disable_hostlink --skip_env_check \
  --ros_domain_id 42 --devices ./lan_demo --external_devices_only \
  --disable_browser --port 8101 -g ./examples/host.json
```

Slave:

```bash
unilab --backend ros2 --disable_hostlink --skip_env_check --is_slave \
  --ros_domain_id 42 --devices ./lan_demo --external_devices_only \
  --disable_browser --port 8102 -g ./examples/slave.json
```

## What is verified

- cross-device status subscription (`counter` and edge-triggered `state`);
- remote `stop_counting` action and its returned result;
- backend-neutral `DeviceNode.call_device_action`;
- strict graph identity (`uuid`, `template_name`, authoritative empty Site snapshots);
- bounded completion via `closed_loops` and the smoke proof JSON.

## Registry-only check

The registry check imports ROS message definitions, so run it in the repository's supported ROS
environment:

```bash
unilab --check_mode --skip_env_check --devices ./lan_demo --external_devices_only
```

## Layout

```text
.
├── examples/host.json
├── examples/slave.json
├── lan_demo/hub_node.py
├── lan_demo/status_reporter.py
├── lan_demo/smoke.py
└── tests/test_hostlink_smoke.py
```
