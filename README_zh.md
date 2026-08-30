# LabDeviceLanDemo

[English](README.md) | **中文**

这是一个有明确终止条件、可直接运行的 Uni-Lab-OS 局域网演示。同一套 hub/sub
驱动同时支持 `hostlink` 和 `ros2`：

1. `status_reporter_demo` 发布 `counter` 与 `state`；
2. `hub_node_demo` 通过跨设备 `@subscribe` 收到状态；
3. 累计 N 次后，hub 远程调用 reporter 的 `stop_counting`；
4. 只有远程动作成功返回，hub 才会上报 `demo_complete=true`。

它不依赖云端库存，也不要求 AK/SK。HTTP 仍是本地微后端数据面，设备间传输由
`--backend` 选择。

## 从 GitHub 安装

新版 Uni-Lab-OS 可以直接接收普通 GitHub 地址，并在安装后识别实际分发名
`lan_demo`：

```bash
unilab package install https://github.com/Xuwznln/LabDeviceLanDemo --ref <commit-sha>
```

## 有限时 smoke

下面的命令会真实启动 host/slave 两个进程，等待 proof JSON，校验 backend 与终态，
然后自动停止两个进程，不再依赖无限日志人工判断。

```bash
# 不需要 ROS
python -m lan_demo.smoke --backend hostlink --timeout 30

# 在 ROS 2 Jazzy/Humble 环境中运行
python -m lan_demo.smoke --backend ros2 --timeout 45
```

成功输出示例：

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

## 默认子工作流

`lan_demo/workflows.py` 用主仓的 `@workflow` 装饰器声明了「LAN 远程轮次控制」：
`echo -> stop_counting -> start_counting` 三步全部指向 slave 图里的 `sub_reporter`。
host 启动时 AST 扫描发现该模块，按函数相对路径派生稳定 uuid 幂等上报到本机
Workflow Authority——重启/重装不会产生重复工作流。

smoke 的阶段二完全通过管理 HTTP API 驱动，等价于用户在前端实时创建并运行工作流：

- `GET /api/v1/workflows` 按显示名检索上报结果；
- `POST /api/v1/workflow-tasks` 创建一次运行（`{"workflow_uuid": ..., "run_mode": "normal"}`）；
- `GET /api/v1/workflow-tasks/{uuid}` 轮询终态；
- `GET /api/v1/workflow-tasks/{uuid}/jobs` 校验每个节点 job 的 `return_info`。

三步同一设备，调度器保证串行；`start_counting` 返回的 `round_index` 严格大于
`stop_counting` 的轮次，证明执行顺序与声明一致。

CI 会通过普通 GitHub URL 加当前精确提交 SHA 安装本仓库，然后切换到 checkout 之外的
临时目录，在同一个 Jazzy job 中运行上面两条命令。每天北京时间 08:00 还会检查
Uni-Lab-OS `dev`；只有该分支出现新 SHA 才重新跑完整 smoke，失败的 SHA 次日继续重试。

## 手动启动 HostLink

Host：

```bash
unilab --backend hostlink --skip_env_check \
  --devices ./lan_demo --external_devices_only \
  --hostlink_bind 0.0.0.0 --hostlink_port 7302 \
  --disable_browser --port 8101 -g ./examples/host.json
```

Slave（跨机器时把地址换成 Host 的局域网 IP/DNS）：

```bash
unilab --backend hostlink --skip_env_check \
  --devices ./lan_demo --external_devices_only --is_slave \
  --host_node_ip 192.168.1.10 --hostlink_port 7302 \
  --disable_browser --port 8102 -g ./examples/slave.json
```

`--hostlink_port` 是设备链路 TCP 端口，和 `--port` 的管理 HTTP 端口互不相干；
HostLink 断开后会持续重连。

## 手动启动 ROS2

两个进程使用相同的 `ROS_DOMAIN_ID` 与同一份 driver/graph。

Host：

```bash
unilab --backend ros2 --disable_hostlink --skip_env_check \
  --ros_domain_id 42 --devices ./lan_demo --external_devices_only \
  --disable_browser --port 8101 -g ./examples/host.json
```

Slave：

```bash
unilab --backend ros2 --disable_hostlink --skip_env_check --is_slave \
  --ros_domain_id 42 --devices ./lan_demo --external_devices_only \
  --disable_browser --port 8102 -g ./examples/slave.json
```

## 验收内容

- 跨设备订阅 `counter`，以及 `state` 的变更触发；
- 远程 `stop_counting` action 和返回值；
- HostLink/ROS2 共用的 `DeviceNode.call_device_action`；
- 新图契约要求的 UUID、template_name、权威空 Site 快照；
- `closed_loops` 和 proof JSON 给出的有限时终态。

仅检查注册表（需要仓库支持的 ROS 环境）：

```bash
unilab --check_mode --skip_env_check --devices ./lan_demo --external_devices_only
```
