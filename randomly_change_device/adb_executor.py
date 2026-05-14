"""ADB 命令执行器（randomly_change_device 精简版）.

包含本模块所需的方法：
- run_shell: 执行 shell 命令
- run_command: 执行任意 ADB 命令（用于 pull）
- push: 推送文件到设备
- reboot: 重启设备
- wait_for_recovery: 等待设备进入 Recovery 模式

不包含: run_streaming_shell（本模块不需要流式 stdin 传输）

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT: int = 30


@dataclass(frozen=True)
class AdbResult:
    """ADB 命令执行的不可变结果."""

    command: str
    stdout: str
    stderr: str
    returncode: int
    success: bool


class AdbError(Exception):
    """当 ADB 命令执行失败时抛出."""

    def __init__(self, message: str, result: AdbResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class AdbExecutor:
    """通过 subprocess.run() 执行 ADB 命令.

    参数:
        adb_path: adb 可执行文件的路径。
        timeout: 默认命令超时时间（秒）。
    """

    def __init__(
        self,
        adb_path: Path | str = "adb",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._adb_path = str(adb_path)
        self._timeout = timeout

    # ── 公共方法 ─────────────────────────────────────────────

    def run_shell(self, command: str, timeout: int | None = None) -> AdbResult:
        """执行 ADB shell 命令."""
        return self._run(["shell", command], timeout=timeout)

    def run_command(self, *args: str, timeout: int | None = None) -> AdbResult:
        """执行任意 ADB 命令（例如 pull）."""
        return self._run(list(args), timeout=timeout)

    def reboot(self, target: str = "", timeout: int | None = None) -> AdbResult:
        """重启设备到指定目标."""
        args = ["reboot", target] if target else ["reboot"]
        return self._run(args, timeout=timeout)

    def push(
        self,
        local_path: Path,
        remote_path: str,
        timeout: int | None = None,
    ) -> AdbResult:
        """推送本地文件到设备."""
        resolved = Path(local_path).resolve()

        if not resolved.exists():
            msg = f"本地文件不存在: {resolved}"
            logger.error(msg)
            raise AdbError(msg)

        if not resolved.is_file():
            msg = f"路径不是文件: {resolved}"
            logger.error(msg)
            raise AdbError(msg)

        logger.info("推送文件: %s → %s", resolved, remote_path)
        return self._run(
            ["push", str(resolved), remote_path],
            timeout=timeout,
        )

    def wait_for_recovery(
        self,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> None:
        """等待设备进入 Recovery 模式（TWRP）.

        TWRP 最佳实践：轮询 adb devices 检测 'recovery' 状态。
        """
        logger.info("等待设备进入 Recovery 模式 (最长 %d 秒)...", timeout)

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                result = self._run(["devices"], timeout=10)

                if result.success and "recovery" in result.stdout:
                    logger.info("设备已进入 Recovery 模式")
                    time.sleep(2)
                    return

            except AdbError:
                pass

            time.sleep(poll_interval)

        msg = f"等待设备进入 Recovery 模式超时 ({timeout} 秒)"
        logger.error(msg)
        raise AdbError(msg)

    # ── 内部方法 ─────────────────────────────────────────────

    def _run(self, args: list[str], timeout: int | None = None) -> AdbResult:
        """使用给定参数运行 adb."""
        effective_timeout = timeout if timeout is not None else self._timeout
        full_cmd = [self._adb_path] + args
        cmd_str = " ".join(full_cmd)

        logger.debug("执行命令: %s", cmd_str)

        try:
            completed = subprocess.run(
                full_cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
            )

            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()

            result = AdbResult(
                command=cmd_str,
                stdout=stdout,
                stderr=stderr,
                returncode=completed.returncode,
                success=completed.returncode == 0,
            )

            logger.debug(
                "执行结果: rc=%d stdout=%r stderr=%r",
                result.returncode,
                result.stdout[:200],
                result.stderr[:200],
            )

            return result

        except FileNotFoundError:
            msg = f"未找到 ADB 可执行文件: {self._adb_path}"
            logger.error(msg)
            raise AdbError(msg) from None

        except subprocess.TimeoutExpired:
            msg = f"ADB 命令在 {effective_timeout} 秒后超时: {cmd_str}"
            logger.error(msg)
            raise AdbError(msg) from None
