# Uni-Lab-OS LAN Demo

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

Requires the unified Uni-Lab-OS core (dev architecture with the V1.0 HTTP API) on
**CPython 3.14**, plus its companion wheels: the maintained PyLabRobot fork
`1.0.0b1+unilabos…` and `opentrons-shared-data 10.1.0+unilabos.np2.1`. Build them with the
core's `scripts/build_wheel_release.py --dependencies-only` and install with `--find-links`.
ROS 2 runs use RoboStack Jazzy built for cp314 (`ros2-distro-mutex` 0.20).

With a Host running (`unilab --backend hostlink`), install through its management API. The
spec is the GitHub URL with an optional `@<commit-sha>`:

```bash
unilab package install https://github.com/Xuwznln/LabDeviceLanDemo@<commit-sha> --wait
```

Or install the distribution into the current Python environment (this is what CI does):

```bash
python -m pip install "git+https://github.com/Xuwznln/LabDeviceLanDemo@<commit-sha>"
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
  "closed_loops": 1,
  "workflow": {
    "workflow_name": "LAN 远程轮次控制",
    "task_status": "succeeded",
    "jobs": [{"status": "succeeded"}, {"status": "succeeded"}, {"status": "succeeded"}]
  }
}
```

## Default sub-workflow

`lan_demo/workflows.py` declares the "LAN 远程轮次控制" workflow with the core
`@workflow` decorator: three steps (`echo -> stop_counting -> start_counting`),
all targeting `sub_reporter` from the slave graph. On host startup the AST scan
discovers the module and the definition is upserted into the local Workflow
Authority as a template under a stable uuid derived from the function path, so restarts and
reinstalls never create duplicates.

Stage two of the smoke drives everything through the management HTTP API, which
is exactly what a frontend does when creating and running workflows live. Every
`/api/v1` JSON response is the V1 envelope `{"code": 0, "data": ...}`, and writes carry the
control token in the `X-UniLab-Token` header (the smoke chooses the token and hands it to the
runtime it starts):

- `GET /api/v1/registry/workflow-templates` finds the reported template by display name;
- `POST /api/v1/workflows/from-template` instantiates it (`{"template_uuid": ..., "bindings": {}}`);
- `POST /api/v1/workflow-tasks` starts one run (`{"workflow_uuid": ..., "run_mode": "normal"}`);
- `GET /api/v1/workflow-tasks/{uuid}` polls the terminal state;
- `GET /api/v1/workflow-tasks/{uuid}/jobs` verifies each node job's `return_info`.

Declarative `@workflow` steps run strictly serially (each node's
`execution_policy.depends_on` points at the previous step and becomes a DAG
dependency edge); the `round_index` returned by `start_counting` is strictly
greater than the round stopped by `stop_counting`, proving declaration-order
execution.

CI (CPython 3.14, RoboStack Jazzy with `ros2-distro-mutex` 0.20) installs this repository
through the ordinary GitHub URL plus the exact commit SHA, changes to a directory outside the
checkout, and then runs the two commands above in one Jazzy job. A
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
  --disable_browser --port 8102 --server_database_root ./slave-data \
  -g ./examples/slave.json
```

On one machine the slave needs its own data directory (`--server_database_root`): one instance owns one database root, and a second instance on the same root exits with code 73.

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
  --disable_browser --port 8102 --server_database_root ./slave-data \
  -g ./examples/slave.json
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
