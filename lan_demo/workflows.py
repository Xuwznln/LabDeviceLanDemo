"""LAN demo 默认子工作流：远程控制子设备的一轮计数。

host 启动时由主仓 AST 扫描发现本模块（@workflow），import 后按稳定 uuid
幂等上报到本机 Workflow Authority，前端/HTTP 可直接引用运行。

三步全部指向 slave 图里的 sub_reporter（host 图之外的设备）：
- 上报时设备不在 host 目录，material_uuid 用稳定占位；
- 调度按节点 meta_data.target_device_id 寻址，经 HostLink 网关路由到 slave；
- 三步同一设备，调度器保证串行，节点 uuid 序 == 声明序。
"""

from unilabos.registry.workflows import WorkflowBuildContext, workflow

#: smoke/测试按显示名检索上报结果，保持单一出处。
REMOTE_ROUND_WORKFLOW_NAME = "LAN 远程轮次控制"


@workflow(
    display_name=REMOTE_ROUND_WORKFLOW_NAME,
    description="回显标记 -> 终止当前轮 -> 立即重开一轮（三步串行，目标为 slave 侧子设备）",
    tags=["lan-demo", "remote-control"],
)
def remote_round_control(ctx: WorkflowBuildContext) -> None:
    """ctx.run 显式指定 device_id：目标设备在 slave 图中，host 图不含它。"""

    ctx.run("sub_reporter/echo", {"message": "workflow-start"}, name="回显开始标记")
    ctx.run("sub_reporter/stop_counting", {}, name="终止当前轮")
    ctx.run("sub_reporter/start_counting", {}, name="重开一轮计数")
