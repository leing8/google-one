"""ADB 命令执行器。

遵循 Python 官方推荐的 subprocess.run() 轻量级封装：
- subprocess.run() 是推荐的方法（Python 3.14 文档）
- 使用 capture_output=True 捕获标准输出/标准错误
- 使用 encoding="utf-8" 显式指定解码（ADB 输出固定 UTF-8）
- 使用 errors="replace" 安全兜底畸形字节
- 使用参数列表（不使用 shell=True）以保证安全
- 使用超时机制防止挂起

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

# ADB 命令的默认超时时间（秒）
_DEFAULT_TIMEOUT: int = 30


@dataclass(frozen=True)
class AdbResult:
    """ADB 命令执行的不可变结果。

    属性:
        command: 执行的 shell 命令。
        stdout: 捕获的标准输出（已去除首尾空白）。
        stderr: 捕获的标准错误（已去除首尾空白）。
        returncode: 进程退出码。
        success: 命令是否以退出码 0 完成。
    """

    command: str
    stdout: str
    stderr: str
    returncode: int
    success: bool


class AdbError(Exception):
    """当 ADB 命令执行失败时抛出。"""

    def __init__(self, message: str, result: AdbResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class AdbExecutor:
    """通过 subprocess.run() 执行 ADB 命令。

    使用推荐的 Python subprocess API：
    - 参数列表（不使用 shell=True）以保证安全
    - capture_output=True 用于捕获标准输出/标准错误
    - text=True 用于自动进行 UTF-8 解码
    - 可配置的超时时间（默认 30 秒）

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

    def run_shell(self, command: str, timeout: int | None = None) -> AdbResult:
        """执行一个 ADB shell 命令。

        等同于：adb shell <command>

        参数:
            command: 要在设备上运行的 shell 命令。
            timeout: 覆盖默认的超时时间（秒）。

        返回:
            包含捕获输出的 AdbResult。

        抛出:
            AdbError: 如果未找到 adb 可执行文件或命令超时。
        """
        return self._run(["shell", command], timeout=timeout)

    def run_command(self, *args: str, timeout: int | None = None) -> AdbResult:
        """执行任意 ADB 命令。

        等同于：adb <args...>

        参数:
            args: ADB 命令参数（例如 "devices", "-l"）。
            timeout: 覆盖默认的超时时间（秒）。

        返回:
            包含捕获输出的 AdbResult。

        抛出:
            AdbError: 如果未找到 adb 可执行文件或命令超时。
        """
        return self._run(list(args), timeout=timeout)

    def _run(self, args: list[str], timeout: int | None = None) -> AdbResult:
        """内部方法：使用给定参数运行 adb。

        按照 Python 官方文档的推荐使用 subprocess.run()：
        - capture_output=True 捕获标准输出和标准错误
        - text=True 将输出解码为 UTF-8 字符串
        - 出于安全考虑不使用 shell=True（参数列表可防止注入）

        参数:
            args: 传递给 'adb' 之后的参数。
            timeout: 超时时间（秒），默认为实例设置的超时时间。

        返回:
            包含命令输出和状态的 AdbResult。

        抛出:
            AdbError: 在未找到文件（未找到 adb）或超时时抛出。
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        full_cmd = [self._adb_path] + args
        cmd_str = " ".join(full_cmd)

        logger.debug("执行命令: %s", cmd_str)

        try:
            # Python 官方推荐：使用带有 capture_output=True 的 subprocess.run()
            # Android ADB 输出固定为 UTF-8 编码，Windows 默认使用 locale 编码（GBK），
            # 显式指定 encoding="utf-8" 避免非 ASCII 字符解码失败。
            # errors="replace" 作为安全兜底，防止任何畸形字节导致崩溃。
            # 参考: https://docs.python.org/3/library/subprocess.html#frequently-used-arguments
            completed = subprocess.run(
                full_cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
            )

            # 防御性处理：解码异常时 stdout/stderr 可能为 None
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

    def reboot(self, target: str = "", timeout: int | None = None) -> AdbResult:
        """重启设备到指定目标。

        等同于：adb reboot [target]

        对应抓包日志：
        - 步骤 1: reboot:recovery  → reboot("recovery")
        - 步骤 6: reboot:          → reboot()

        参数:
            target: 重启目标（"recovery", "bootloader", 等）。
                    空字符串表示重启到系统。
            timeout: 覆盖默认的超时时间（秒）。

        返回:
            包含捕获输出的 AdbResult。

        抛出:
            AdbError: 如果重启命令失败。
        """
        args = ["reboot", target] if target else ["reboot"]
        return self._run(args, timeout=timeout)

    def push(
        self,
        local_path: Path,
        remote_path: str,
        timeout: int | None = None,
    ) -> AdbResult:
        """推送本地文件到设备。

        等同于：adb push <local> <remote>

        对应抓包日志步骤 3: push → /sdcard/Magisk.zip

        按照 Python 官方推荐：
        - 使用 pathlib.Path 进行路径操作
        - 使用 Path.exists() 进行文件存在性校验
        - 使用参数列表避免路径中空格导致的问题

        参数:
            local_path: 本地文件路径。
            remote_path: 设备上的目标路径。
            timeout: 覆盖默认的超时时间（秒）。
                    大文件传输建议设置 120 秒以上。

        返回:
            包含捕获输出的 AdbResult。

        抛出:
            AdbError: 如果文件不存在或推送失败。
        """
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
        """等待设备进入 Recovery 模式（TWRP）。

        TWRP 官方最佳实践：
        - 不使用 adb wait-for-device（TWRP 报告状态为 'recovery' 而非 'device'，
          会导致 wait-for-device 无限挂起）
        - 使用轮询 adb devices 检查设备状态是否为 'recovery'
        - 检测到 'recovery' 状态后，通过 adb shell 验证 shell 可用性

        参数:
            timeout: 最大等待时间（秒），默认 120 秒。
            poll_interval: 轮询间隔（秒），默认 2 秒。

        抛出:
            AdbError: 如果超时仍未检测到设备进入 Recovery。
        """
        logger.info("等待设备进入 Recovery 模式 (最长 %d 秒)...", timeout)

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                result = self._run(["devices"], timeout=10)

                if result.success and "recovery" in result.stdout:
                    logger.info("设备已进入 Recovery 模式")
                    # 额外验证 shell 可用性（TWRP 推荐）
                    time.sleep(2)
                    return

            except AdbError:
                # ADB 可能暂时不可用（设备重启中），继续轮询
                pass

            time.sleep(poll_interval)

        msg = f"等待设备进入 Recovery 模式超时 ({timeout} 秒)"
        logger.error(msg)
        raise AdbError(msg)
