"""有限时启动真实 hub/sub 进程并验证订阅 + 远程动作闭环。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from typing import Any, Sequence


def assert_smoke_proof(proof: dict[str, Any], backend: str) -> None:
    """对 HostLink/ROS2 共用的订阅、状态变化和远程动作结果做同一组断言。"""

    assert proof.get("success") is True, f"smoke 未成功: {proof}"
    assert proof.get("backend") == backend, f"backend 不匹配: {proof}"
    assert proof["subscribed_counter"] > 0
    assert proof["terminate_after"] == 3
    assert proof["trigger_received_count"] >= proof["terminate_after"]
    assert 0 <= proof["received_count"] <= proof["trigger_received_count"]
    assert proof["terminations"] == 1
    assert proof["closed_loops"] == 1
    assert isinstance(proof["pending_reset"], bool)
    assert proof["remote_action"] == "stop_counting"
    assert proof["last_action"] == (
        f"closed-loop@{proof['subscribed_counter']} (#1)"
    )
    transitions = proof["control_transitions"]
    assert transitions[0] == "idle"
    assert "terminating" in transitions
    assert "closed_loop" in transitions
    assert transitions.index("terminating") < transitions.index("closed_loop")

    remote_result = proof["remote_result"]
    assert remote_result["success"] is True
    assert remote_result["node_label"] == "sub"
    assert remote_result["round_index"] == 1
    assert remote_result["stopped_at"] >= proof["subscribed_counter"]
    assert remote_result["state"] == "paused"
    assert remote_result["counter"] == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _stop(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _graph_path(repo_root: Path, filename: str) -> Path:
    """优先读取 wheel 安装的数据文件，editable/source 模式回退到仓库 examples。"""

    installed = (
        Path(sysconfig.get_path("data"))
        / "share"
        / "lan_demo"
        / "examples"
        / filename
    )
    if installed.is_file():
        return installed
    source = repo_root / "examples" / filename
    if source.is_file():
        return source
    raise FileNotFoundError(f"LAN demo graph 未随 distribution 安装: {filename}")


def _base_command(
    repo_root: Path,
    graph: Path,
    database_root: Path,
    management_port: int,
    backend: str,
) -> list[str]:
    import unilabos

    config_path = Path(unilabos.__file__).resolve().parent / "config" / "example_config.py"
    command = [
        sys.executable,
        "-m",
        "unilabos",
        "--backend",
        backend,
        "--skip_env_check",
        "--devices",
        str(repo_root / "lan_demo"),
        "--external_devices_only",
        "--visual",
        "disable",
        "--disable_browser",
        "--port",
        str(management_port),
        "--server_database_root",
        str(database_root),
        "--working_dir",
        str(database_root / "work"),
        "--config",
        str(config_path),
        "-g",
        str(graph),
    ]
    if backend == "ros2":
        command.append("--disable_hostlink")
    return command


def run_smoke(backend: str = "hostlink", timeout: float = 30.0) -> dict[str, Any]:
    """运行有终止条件的双进程 smoke；成功时返回 hub 写出的终态 JSON。"""
    if backend not in {"hostlink", "ros2"}:
        raise ValueError("backend must be hostlink or ros2")
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=f"lan-demo-{backend}-") as directory:
        root = Path(directory)
        proof_path = root / "proof.json"
        environment = os.environ.copy()
        environment.update(
            {
                "LAN_DEMO_PROOF_FILE": str(proof_path),
                "LAN_DEMO_TERMINATE_AFTER": "3",
                "LAN_DEMO_COUNT_RATE": "100",
                "LAN_DEMO_CYCLE_PAUSE": "60",
                "PYTHONUNBUFFERED": "1",
            }
        )
        host_log_path = root / "host.log"
        slave_log_path = root / "slave.log"
        hostlink_port = _free_port()
        host_command = _base_command(
            repo_root,
            _graph_path(repo_root, "host.json"),
            root / "host-db",
            _free_port(),
            backend,
        )
        slave_command = _base_command(
            repo_root,
            _graph_path(repo_root, "slave.json"),
            root / "slave-db",
            _free_port(),
            backend,
        ) + ["--is_slave"]
        if backend == "hostlink":
            host_command += [
                "--hostlink_bind",
                "127.0.0.1",
                "--hostlink_port",
                str(hostlink_port),
            ]
            slave_command += [
                "--host_node_ip",
                "127.0.0.1",
                "--hostlink_port",
                str(hostlink_port),
            ]
        else:
            domain_id = str(10 + hostlink_port % 190)
            environment["ROS_DOMAIN_ID"] = domain_id
            host_command += ["--ros_domain_id", domain_id]
            slave_command += ["--ros_domain_id", domain_id]

        with host_log_path.open("w", encoding="utf-8") as host_log, slave_log_path.open(
            "w", encoding="utf-8"
        ) as slave_log:
            host = subprocess.Popen(
                host_command,
                cwd=repo_root,
                env=environment,
                stdout=host_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            slave: subprocess.Popen[Any] | None = None
            try:
                startup_deadline = time.monotonic() + min(8.0, timeout / 2)
                while time.monotonic() < startup_deadline:
                    if host.poll() is not None:
                        break
                    if backend == "hostlink":
                        try:
                            with socket.create_connection(
                                ("127.0.0.1", hostlink_port), timeout=0.2
                            ):
                                break
                        except OSError:
                            pass
                    else:
                        # ROS graph discovery has no TCP readiness port; a short bounded grace
                        # period lets the host service and topic graph appear.
                        time.sleep(1.0)
                        break
                    time.sleep(0.05)
                if host.poll() is not None:
                    host_log.flush()
                    raise RuntimeError(
                        "host process exited before slave startup\n"
                        + host_log_path.read_text(encoding="utf-8", errors="replace")
                    )
                slave = subprocess.Popen(
                    slave_command,
                    cwd=repo_root,
                    env=environment,
                    stdout=slave_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if proof_path.is_file():
                        proof = json.loads(proof_path.read_text(encoding="utf-8"))
                        assert_smoke_proof(proof, backend)
                        return proof
                    if host.poll() is not None or slave.poll() is not None:
                        break
                    time.sleep(0.1)
                raise RuntimeError(
                    f"{backend} smoke did not complete within {timeout}s\n"
                    f"HOST:\n{host_log_path.read_text(encoding='utf-8', errors='replace')}\n"
                    f"SLAVE:\n{slave_log_path.read_text(encoding='utf-8', errors='replace')}"
                )
            finally:
                if slave is not None:
                    _stop(slave)
                _stop(host)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("hostlink", "ros2"), default="hostlink")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    print(json.dumps(run_smoke(args.backend, args.timeout), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
