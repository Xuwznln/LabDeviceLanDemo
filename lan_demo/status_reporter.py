"""
子设备 - 状态上报 Demo (StatusReporterDemo)

职责单一：只负责「自增长 + 周期上报状态」，不做任何控制判断。

- counter 自增长（默认 4 个/秒），通过 @topic_config 周期发布到 /devices/<id>/counter；
- 同时发布 heartbeat、state，局域网内任何节点（尤其是中枢节点）都能订阅；
- 暴露 stop_counting 动作：被中枢节点通过 ros action 调用以「终止当前轮」，
  终止后暂停 cycle_pause 秒自动开下一轮，从 0 重新增长（counter 呈锯齿形，便于持续演示）。

它本身不知道、也不关心谁在订阅它、谁来终止它 —— 控制逻辑全在中枢节点。
"""

import logging
import threading
import time
from typing import Any, Optional

from typing_extensions import TypedDict

from unilabos.registry.decorators import action, device, not_action, topic_config


class StopResult(TypedDict):
    """stop_counting 返回类型。"""

    success: bool
    node_label: str
    stopped_at: int
    round_index: int


@device(
    id="status_reporter_demo",
    display_name="子设备-状态上报",
    category=["virtual_device"],
    description="子设备：counter 自增长并周期上报状态；可被中枢节点通过 ros action 终止当前轮",
)
class StatusReporterDemo:
    """子设备：counter 自增长 + 周期上报；stop_counting 可被远程 ros action 终止当前轮。"""

    def __init__(
        self,
        device_id: Optional[str] = None,
        node_label: str = "sub",
        count_rate: float = 4.0,
        cycle_pause: float = 5.0,
        auto_start: bool = True,
        **kwargs,
    ):
        """初始化子设备。

        Args:
            device_id[设备ID]: 设备实例 ID，默认 status_reporter_demo。
            node_label[节点标签]: 节点角色标签，例如 sub。
            count_rate[计数速率(个/秒)]: counter 每秒增长多少。
            cycle_pause[轮次间隔(s)]: 被终止后暂停多久再自动开下一轮。
            auto_start[自动启动]: 是否在 post_init 后自动开始自增长（默认 True）。
        """
        self.device_id = device_id or "status_reporter_demo"
        self.node_label = node_label
        self._count_rate = float(count_rate)
        self._cycle_pause = float(cycle_pause)
        self._auto_start = bool(auto_start)
        self.logger = logging.getLogger(f"StatusReporter.{self.device_id}")

        self._ros_node: Any = None
        self._start_time: float = time.time()
        self._grow_begin: float = time.time()
        self._counter: int = 0
        self._paused: bool = True  # 默认暂停，post_init 自动开第一轮
        self._round_index: int = 0

        self.logger.info(f"=== 子设备-状态上报 {self.device_id} 已创建 (label={self.node_label}) ===")

    @not_action
    def post_init(self, ros_node: Any):
        """ROS 节点初始化后回调：拿到 _ros_node，并按需自动开第一轮。"""
        self._ros_node = ros_node
        if self._auto_start:
            self._begin_round()

    @not_action
    def _begin_round(self) -> None:
        """开启新一轮自增长：counter 归零并从现在开始增长。"""
        self._round_index += 1
        self._grow_begin = time.time()
        self._counter = 0
        self._paused = False
        self.logger.info(f"[REPORT][{self.node_label}] 第 {self._round_index} 轮开始：counter 从 0 自增长")

    @not_action
    def _resume_after_pause(self) -> None:
        """终止后等待 cycle_pause 秒，再自动开下一轮。"""
        time.sleep(self._cycle_pause)
        self._begin_round()

    # ============ 周期上报的状态 ============

    @property
    @topic_config(period=0.5)
    def counter(self) -> int:
        """自增长计数器；暂停（被终止）期间停在 0（多次读取安全无副作用）。"""
        if not self._paused:
            self._counter = int((time.time() - self._grow_begin) * self._count_rate)
        return self._counter

    @property
    @topic_config(period=1.0)
    def heartbeat(self) -> int:
        """自启动以来的心跳秒数。"""
        return int(time.time() - self._start_time)

    @property
    @topic_config()
    def state(self) -> str:
        """当前状态：running / paused。"""
        return "paused" if self._paused else "running"

    # ============ 可被中枢节点远程调用的动作 ============

    @action(
        description="终止当前轮 counter 自增长（中枢节点通过 ros action 调用），随后自动开下一轮",
        always_free=True,
        feedback_interval=1.0,
    )
    def stop_counting(self) -> StopResult:
        """终止当前轮自增长（counter 归零并暂停），cycle_pause 秒后自动开下一轮。"""
        stopped_at = self._counter
        self._paused = True
        self._counter = 0
        self.logger.info(
            f"[REPORT][{self.node_label}] stop_counting：第 {self._round_index} 轮被终止于 {stopped_at}，"
            f"{self._cycle_pause}s 后自动开下一轮"
        )
        threading.Thread(target=self._resume_after_pause, daemon=True).start()
        return {
            "success": True,
            "node_label": self.node_label,
            "stopped_at": stopped_at,
            "round_index": self._round_index,
        }

    @action(description="立即开始一轮自增长（手动）", always_free=True, feedback_interval=1.0)
    def start_counting(self) -> dict:
        """立即开启新一轮自增长。"""
        self._begin_round()
        return {"success": True, "node_label": self.node_label, "round_index": self._round_index}

    @action(description="回显消息（通用被调用目标）", always_free=True, feedback_interval=1.0)
    def echo(self, message: str = "ping") -> dict:
        """回显收到的消息，可作为跨设备调用的通用目标。

        Args:
            message[消息内容]: 任意字符串，将被原样回显。
        """
        self.logger.info(f"[REPORT][{self.node_label}] echo 收到调用: {message}")
        return {"success": True, "node_label": self.node_label, "reply": f"[{self.node_label}] echo => {message}"}
