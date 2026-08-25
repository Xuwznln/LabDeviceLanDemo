from __future__ import annotations

from lan_demo.smoke import assert_smoke_proof, run_smoke


def test_real_hub_sub_hostlink_smoke() -> None:
    proof = run_smoke("hostlink", timeout=20.0)
    assert_smoke_proof(proof, "hostlink")
