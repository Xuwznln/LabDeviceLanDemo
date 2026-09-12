"""LAN demo 默认子工作流：远程控制子设备的一轮计数。

host 启动时由主仓 AST 扫描发现本模块（@workflow），import 后按稳定 uuid
幂等上报到本机 Workflow Authority，前端/HTTP 可直接引用运行。

三步全部指向 slave 图里的 sub_reporter（host 图之外的设备）：
- 上报时设备不在 host 目录，material_uuid 用稳定占位；
- 调度按节点 meta_data.target_device_id 寻址，经 HostLink 网关路由到 slave；
- 三步严格串行（execution_policy.depends_on 依赖边），节点 uuid 序 == 声明序。
"""

from unilabos.registry.workflows import WorkflowBuildContext, WorkflowGuide, workflow

#: smoke/测试按显示名检索上报结果，保持单一出处。
REMOTE_ROUND_WORKFLOW_NAME = "LAN 远程轮次控制"


@workflow(
    display_name=REMOTE_ROUND_WORKFLOW_NAME,
    description="回显标记 -> 终止当前轮 -> 立即重开一轮（三步串行，目标为 slave 侧子设备）",
    tags=["lan-demo", "remote-control"],
    guide=WorkflowGuide(
        preparation=[
            "按 README 启动 hub（host）与 sub（slave）两个进程；「设备」页确认 sub_reporter 在线且显示为远程设备。",
            "无需准备物料：三步都是对 slave 侧子设备的远程控制。",
        ],
        expected=[
            "任务 succeeded，三步全部成功。",
            "「回显开始标记」返回 workflow-start；「运行监控」里 sub_reporter 的计数状态先停止、再从 0 重新增长。",
            "hub 进程日志里能看到经 HostLink 路由到 slave 的三次调用。",
        ],
        notes=["目标设备不在 host 图里：模板用显式设备 id sub_reporter 作角色，插入时如果设备 id 不同请手选。"],
    ),
)
def remote_round_control(ctx: WorkflowBuildContext) -> None:
    """ctx.run 显式指定 device_id：目标设备在 slave 图中，host 图不含它。"""

    ctx.run(
        "sub_reporter/echo",
        {"message": "workflow-start"},
        name="回显开始标记",
        description="让 slave 侧子设备原样回显一条标记，验证 HostLink 链路通。",
    )
    ctx.run(
        "sub_reporter/stop_counting",
        {},
        name="终止当前轮",
        description="停止子设备当前这一轮计数。",
    )
    ctx.run(
        "sub_reporter/start_counting",
        {},
        name="重开一轮计数",
        description="立即重新开始一轮，计数从 0 增长。",
    )
