from __future__ import annotations

from lan_demo.smoke import assert_smoke_proof, assert_workflow_proof, run_smoke


def test_real_hub_sub_hostlink_smoke() -> None:
    proof = run_smoke("hostlink", timeout=40.0)
    # 阶段一：跨设备订阅 + 远程动作闭环
    assert_smoke_proof(proof, "hostlink")
    # 阶段二：默认子工作流已上报，可通过管理 API 检索、运行并全部成功
    assert_workflow_proof(proof["workflow"])
