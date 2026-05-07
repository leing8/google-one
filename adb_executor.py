"""ADB 命令执行器。

遵循 Python 官方推荐的 subprocess.run() 轻量级封装：
- subprocess.run() 是推荐的方法（Python 3.14 文档）
- 使用 capture_output=True 捕获标准输出/标准错误
- 使用 text=True 自动进行字符串解码
- 使用参数列表（不使用 shell=True）以保证安全
- 使用超时机制防止挂起

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
"""

from __future__ import annotations

import logging
import subprocess
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
            # Python 官方推荐：使用带有 capture_output=True 和 text=True 的 subprocess.run()
            completed = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )

            result = AdbResult(
                command=cmd_str,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
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
