"""
中枢节点 Demo (HubNodeDemo)

职责单一：只负责「订阅 + 判断 + 控制」，自己不产生 counter。

闭环（跨设备）：
    子设备 status_reporter (counter 自增长发布)
            │  ① 跨设备 @subscribe
            ▼
    中枢 hub_node.on_sub_counter(累计收到次数)
            │  ② if 判断：从第一次收到开始累计满 terminate_after 次
            ▼
    DeviceNode.call_device_action(sub, "stop_counting")  ③ 跨设备终止子设备当前轮

要点：
- @subscribe(device_id="sub_reporter", status_name="counter")：跨设备订阅子设备状态 topic，
  自动补全为 /devices/sub_reporter/counter，msg_type 自动从 ROS 图识别（无类型时循环重试，
  默认 10s、不设上限直到订上），回调值经 msg convert 转换直接拿到 int。
- on_sub_counter 里走 if 判断：累计收到 terminate_after(默认20) 次，就远程终止子设备。
- 子设备被终止后 counter 归零（暂停），中枢据此识别「轮次重置」，自动开始下一轮计数，循环往复。
- 中枢自身只发布 received_count / terminations / last_action 等控制状态，便于面板展示。

注意：@subscribe 的目标设备 id 是装饰器常量（静态），固定为 SUB_DEVICE_ID="sub_reporter"，
需与子设备在图里的节点 id 一致；动作调用目标 sub_device 可由 config 覆盖（默认同值）。
"""

import logging
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Optional

from unilabos.registry.decorators import action, device, not_action, topic_config
from unilabos.registry.placeholder_type import DeviceSlot
from unilabos.utils.decorator import subscribe

# 子设备节点 id（需与 slave.json 中子设备的 node id 一致）。@subscribe 是静态装饰器，故用常量。
SUB_DEVICE_ID = "sub_reporter"


@device(
    id="hub_node_demo",
    display_name="中枢节点",
    category=["virtual_device"],
    description="中枢节点：跨设备订阅子设备 counter，累计满 N 次后远程终止子设备当前轮",
    supported_backends=["hostlink", "ros2"],
)
class HubNodeDemo:
    """中枢节点：跨设备订阅 counter，再经共用 DeviceNode 调用远程动作。"""

    run_in_test_mode = True

    def __init__(
        self,
        device_id: Optional[str] = None,
        node_label: str = "hub",
        sub_device: str = SUB_DEVICE_ID,
        terminate_after: int = 20,
        **kwargs,
    ):
        """初始化中枢节点。

        Args:
            device_id[设备ID]: 设备实例 ID，默认 hub_node_demo。
            node_label[节点标签]: 节点角色标签，例如 hub。
            sub_device[子设备ID]: 要终止的子设备节点 ID（动作调用目标），需与订阅目标一致，默认 sub_reporter。
            terminate_after[终止阈值(收到次数)]: 从第一次收到开始累计多少次后远程终止子设备。
        """
        self.device_id = device_id or "hub_node_demo"
        self.node_label = node_label
        self._sub_device = (sub_device or SUB_DEVICE_ID).strip()
        self._terminate_after = int(
            os.environ.get("LAN_DEMO_TERMINATE_AFTER", terminate_after)
        )
        self.logger = logging.getLogger(f"HubNode.{self.device_id}")

        self._device_node: Any = None
        self._start_time: float = time.time()
        self._recv_count: int = 0  # 本轮从第一次收到开始累计收到的次数
        self._terminations: int = 0  # 累计触发终止的总次数
        self._closed_loops: int = 0  # 已确认远程动作成功的闭环次数
        self._last_action: str = "（暂无）"
        self._pending_reset: bool = False  # 已触发终止、等待子设备归零
        self._trigger_received_count: int = 0
        self._control_transitions: list[str] = ["idle"]

        self.logger.info(
            f"=== 中枢节点 {self.device_id} 已创建 (label={self.node_label}, sub={self._sub_device}) ==="
        )

    @not_action
    def post_init(self, node: Any):
        """绑定 HostLink/ROS2 共用的 DeviceNode。"""
        self._device_node = node
        self.logger.info(
            f"[HUB][{self.node_label}] 已就绪：跨设备订阅 {self._sub_device}.counter，"
            f"累计满 {self._terminate_after} 次 -> {self._sub_device}.stop_counting 终止"
        )

    # ============ 中枢自身的控制状态（便于面板展示）============

    @property
    @topic_config(period=1.0)
    def heartbeat(self) -> int:
        """自启动以来的心跳秒数。"""
        return int(time.time() - self._start_time)

    @property
    @topic_config(period=0.5)
    def received_count(self) -> int:
        """本轮已累计收到子设备 counter 的次数。"""
        return self._recv_count

    @property
    @topic_config()
    def terminations(self) -> int:
        """累计触发终止子设备的总次数。"""
        return self._terminations

    @property
    @topic_config()
    def closed_loops(self) -> int:
        """已收到远程动作成功返回的闭环次数。"""
        return self._closed_loops

    @property
    @topic_config()
    def demo_complete(self) -> bool:
        """有限时 smoke 可据此判断订阅 + 远程动作已完成。"""
        return self._closed_loops > 0

    @property
    @topic_config()
    def last_action(self) -> str:
        """最近一次控制动作描述。"""
        return self._last_action

    # ============ 跨设备订阅 + if 判断 + 远程动作终止 ============

    @subscribe(device_id=SUB_DEVICE_ID, status_name="counter", retry_interval=10.0)
    def on_sub_counter(self, value) -> None:
        """跨设备订阅子设备 counter 的回调。

        - device_id+status_name 拆分写法 -> 订阅 /devices/sub_reporter/counter；
        - 不写 msg_type：框架默认就会循环重试解析类型（retry_interval 仅自定义周期，这里设 10s），
          子设备一上线就从 ROS 图识别出类型并建立订阅，不受 host/slave 启动先后影响
          （回调首参不要加 Python 内置注解，否则会被当成 msg_type）；
        - 回调值经 msg convert 转换，这里直接拿到 int 值；
        - if 判断：累计满 terminate_after 次，就用共用 DeviceNode 终止子设备。
        """
        # 子设备暂停/重置时 counter=0：作为「轮次重置」信号，不计入计数
        if value <= 0:
            if self._pending_reset:
                self._pending_reset = False
                self._recv_count = 0
                self._control_transitions.append("reset_observed")
                self.logger.info(f"[HUB][{self.node_label}] 检测到子设备已终止/重置，开始下一轮计数")
            return

        if self._pending_reset:
            return  # 已触发终止，等待子设备归零，期间在途的高值忽略

        self._recv_count += 1
        self.logger.info(
            f"[HUB][{self.node_label}] 第 {self._recv_count} 次收到 {self._sub_device}.counter = {value}"
        )

        # if 判断：累计收到次数达到阈值 -> 执行远程动作终止子设备
        if self._recv_count >= self._terminate_after:
            self._pending_reset = True
            self._terminations += 1
            self._trigger_received_count = self._recv_count
            self._control_transitions.append("terminating")
            self._last_action = f"terminate@{value} (#{self._terminations})"
            self.logger.info(
                f"[HUB][{self.node_label}] 已累计收到 {self._recv_count} 次（阈值 {self._terminate_after}），"
                f"执行远程动作 {self._sub_device}.stop_counting 终止子设备"
            )
            threading.Thread(target=self._terminate_sub, args=(value,), daemon=True).start()

    @subscribe(device_id=SUB_DEVICE_ID, status_name="state", trigger_when_change=True, retry_interval=10.0)
    def on_sub_state(self, state) -> None:
        """演示 trigger_when_change：子设备 state 持续发布，但只在 running<->paused 真正切换时才触发。

        同样不写 msg_type，靠 retry_interval 循环重试自动识别为 String。
        """
        self.logger.info(f"[HUB][{self.node_label}] 子设备状态变化 -> {state}")

    @not_action
    def _terminate_sub(self, value: int) -> None:
        """在独立线程里终止子设备当前轮（避免阻塞订阅回调线程）。"""
        try:
            reply = self._device_node.call_device_action(
                self._sub_device,
                "stop_counting",
                {},
                server_wait_timeout=5.0,
                timeout=5.0,
            )
            self._closed_loops += 1
            self._control_transitions.append("closed_loop")
            self._last_action = f"closed-loop@{value} (#{self._closed_loops})"
            self._write_smoke_proof(value, reply)
            self.logger.info(f"[HUB][{self.node_label}] 远程终止子设备成功: {reply}")
        except Exception as ex:  # noqa: BLE001 - 演示用，打印任何远端错误
            self._last_action = f"终止失败: {ex}"
            self.logger.warning(f"[HUB][{self.node_label}] 终止子设备失败: {ex}")

    @not_action
    def _write_smoke_proof(self, value: int, reply: Any) -> None:
        """按需写出有限时 smoke 证据；正常演示不设置环境变量就不会写文件。"""
        target = os.environ.get("LAN_DEMO_PROOF_FILE", "").strip()
        if not target:
            return
        proof_path = Path(target).expanduser().resolve()
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "success": True,
            "backend": str(getattr(self._device_node, "backend_name", "unknown")),
            "subscribed_counter": int(value),
            "received_count": self._recv_count,
            "trigger_received_count": self._trigger_received_count,
            "terminate_after": self._terminate_after,
            "terminations": self._terminations,
            "remote_action": "stop_counting",
            "remote_result": reply,
            "closed_loops": self._closed_loops,
            "last_action": self._last_action,
            "pending_reset": self._pending_reset,
            "control_transitions": list(self._control_transitions),
        }
        temporary = proof_path.with_suffix(proof_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(proof_path)
