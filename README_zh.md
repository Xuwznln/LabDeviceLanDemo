# device_package_lan_demo

[English](README.md) | **中文**

Uni-Lab-OS 外部设备包示例，演示**局域网跨设备闭环**：中枢节点 host 与子设备 slave 分进程运行，
演示 `@subscribe` 跨设备订阅 + `call_device_action` 走 ros action 远程控制的完整闭环。

## 包含的设备

| 设备 class             | 类                   | 角色                                                       |
| ---------------------- | -------------------- | ---------------------------------------------------------- |
| `hub_node_demo`        | `HubNodeDemo`        | 中枢节点：跨设备订阅子设备 `counter`，满 N 次后 ros action 终止子设备 |
| `status_reporter_demo` | `StatusReporterDemo` | 子设备：`counter` 自增长并周期上报，可被远程终止当前轮      |

## 前置条件

```bash
mamba activate unilab          # ROS 2 (humble) + unilabos 环境
cd <repo-root>                 # 所有命令均在 Uni-Lab-OS 仓库根目录执行
```

> **凭据是必填的。** `unilabos.app.main` 在未提供 `--ak` / `--sk` 时会立即退出（它需要一个云端
> 实验室）。可复用 IDE「test」运行配置里的 AK/SK/addr（或你在 <https://leap-lab.bohrium.com>
> 注册的账号）。`--upload_registry` 是唯一可选的云端参数（用于上报注册表，想更快启动可去掉）。
> **没有完全离线模式**——`--ak/--sk/--addr` 必须始终带上。

---

## 闭环逻辑

```
子设备 sub_reporter：counter 自增长（4/s）-> @topic_config 发布 /devices/sub_reporter/counter
        │  ① 跨设备 @subscribe
        ▼
中枢 hub.on_sub_counter：累计收到消息的次数
        │  ② if 判断：从第一次收到起累计满 terminate_after（默认 20）次
        ▼
call_device_action(sub_reporter, "stop_counting")  ③ 走 ros action 终止子设备当前轮
        │
        ▼
子设备 counter 归零（暂停 cycle_pause 秒）-> 中枢识别「轮次重置」-> 自动开始下一轮，循环往复
```

### 演示到的框架能力

- **跨设备 `@subscribe`**：`@subscribe(device_id="sub_reporter", status_name="counter")`
  订阅 *其它设备* 的状态 topic。`@subscribe` 仅用于跨设备；本设备自己的状态直接读 getter 即可。
- **msg_type 自动识别 + 循环重试直到订上**：不写 `msg_type`，框架按周期（默认 10s、
  **不设上限直到订上**）重试解析类型，子设备一上线就从 ROS 图识别类型并建立订阅，
  **不受 host/slave 启动先后影响**。`retry_interval` 仅用于自定义重试周期。
  > 注意：用自动识别时，回调首参**不要**加 Python 内置类型注解（如 `value: int`），否则会被当成 `msg_type`。
- **回调取值经 msg convert**：回调值统一经 `convert_from_ros_msg` 转换，
  `std_msgs` 基础消息直接得到原生值（`Int32 -> int`、`String -> str`），复合消息得到 dict。
- **`trigger_when_change`**：`on_sub_state` 订阅子设备 `state`，持续发布但只在
  `running <-> paused` 真正切换时才触发回调（去抖 / 边沿触发）。
- **`call_device_action`（跨设备调用）**：
  `self._ros_node.call_device_action(device, action, kwargs_dict)` 入参传 **dict**（序列化由框架内部完成），
  自动探测走原生 ros action 还是 serial 指令通道，结果统一解析成 dict/原生值返回；
  远端失败会抛 `DeviceActionError`。

---

## 启动教学（host 先、slave 后；本机两进程即可）

两个进程都扫描同一个包（`--devices ./device_package_lan_demo/lan_demo`）并加 `--external_devices_only`，
仅图文件与 `--is_slave` 不同。**务必先启动 host，再启动 slave**（slave 默认会等待 host 服务）。

**第 1 步 — 启动 host（中枢节点）：**

```bash
python -m unilabos.app.main \
  --devices ./device_package_lan_demo/lan_demo \
  --external_devices_only \
  --ak <你的AK> --sk <你的SK> --addr test --upload_registry \
  --disable_browser --port 8101 \
  -g ./device_package_lan_demo/examples/host.json
```

**第 2 步 — 另开一个终端，启动 slave（子设备）：**

```bash
python -m unilabos.app.main \
  --devices ./device_package_lan_demo/lan_demo \
  --external_devices_only --is_slave \
  --ak <你的AK> --sk <你的SK> --addr test --upload_registry \
  --disable_browser --port 8102 \
  -g ./device_package_lan_demo/examples/slave.json
```

> PyCharm：复制现有「test」运行配置（Module 指向 `unilabos.app.main`，保留其中的 AK/SK/addr 环境），
> 分别建 host / slave 两份，Parameters 改成上面对应内容。
> 真正跨机时，把两份配置放到同一局域网的两台机器上、保证 `ROS_DOMAIN_ID` 一致即可。

### 预期现象（已实测）

本教程已端到端跑通，子设备日志会这样循环：

```
[REPORT][sub] 第 1 轮开始：counter 从 0 自增长
[REPORT][sub] stop_counting：第 1 轮被终止于 25，5.0s 后自动开下一轮
[REPORT][sub] 第 2 轮开始：counter 从 0 自增长
[REPORT][sub] stop_counting：第 2 轮被终止于 19，5.0s 后自动开下一轮
…… 持续循环 ……
```

每次 `stop_counting` 都是中枢累计收到 20 次 `counter` 后远程触发的——证明跨设备订阅、
ros action 远程调用、轮次重置识别均工作正常。还可单独停掉 slave 再重启：host 会自动重新发现
（DDS re-discovery）并重新订阅，无需重启 host。

### 手动跨设备调用（可选）

中枢动作 `hub_node.call_peer(target_device, function_name, function_args)`：
- `function_args` 是 UI 传来的 **JSON 字符串**，动作内部 `json.loads` 成 dict 后传给 `call_device_action`；
- 例如调用子设备的通用回显：`function_name="echo"`、`function_args={"message": "hello"}`。

### 停止

对每个进程按 `Ctrl+C`（或 kill 两个 PID）。

---

## 本地验证（注册表 check，不启动）

```bash
cd device_package_lan_demo
unilab --check_mode --devices ./lan_demo --external_devices_only
```

## 常见问题

- 启动后立刻退出并提示「请前往 … 注册实验室」：`--ak/--sk` 缺失或无效。它们是必填的（见前置条件）。
- `[MessageProcessor] 收到服务端注册码 200, 上一进程可能还未退出`，并不断重连：同一账号的云端
  会话残留。它只影响云端同步，**不影响**本地 ROS 闭环。
- slave 启动卡住：确认**先启动了 host**（slave 默认会等待 host 服务）；加 `--slave_no_host` 可跳过等待。
- 端口被占用：给 host 与 slave 设置**不同**的 `--port`。

## 目录结构

```
device_package_lan_demo/
├── README.md                     # English
├── README_zh.md                  # 中文（本文件）
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .github/workflows/check_registry.yml
├── examples/                     # 跨设备 host/slave 图文件
│   ├── host.json                 # 中枢节点（host）
│   └── slave.json                # 子设备（slave，--is_slave）
└── lan_demo/                     # 被 --devices 扫描的 python 包
    ├── __init__.py
    ├── hub_node.py               # HubNodeDemo（中枢）
    └── status_reporter.py        # StatusReporterDemo（子设备）
```
