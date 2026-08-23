from __future__ import annotations

from lan_demo.smoke import run_smoke


def test_real_hub_sub_hostlink_smoke() -> None:
    proof = run_smoke("hostlink", timeout=20.0)
    assert proof["closed_loops"] == 1
    assert proof["received_count"] >= 3
    assert proof["remote_action"] == "stop_counting"
    assert proof["remote_result"]["success"] is True
