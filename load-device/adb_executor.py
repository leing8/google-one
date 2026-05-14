"""
ADB 命令执行器。

封装 subprocess.run() 调用 adb shell，遵循 Python 官方推荐的最佳实践：
- 使用参数列表而非字符串（避免 shell 注入）
- 不使用 shell=True
- 使用 capture_output=True + text=True 捕获输出
- 使用 timeout 防止挂起
- 对非零返回码不抛异常（shell 命令返回非零可能是正常业务逻辑）

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/subprocess.html#security-considerations
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .models import CommandResult, DeviceInfo

logger = logging.getLogger(__name__)

# ADB 命令执行的默认超时（秒）
_DEFAULT_TIMEOUT: float = 30.0

# Windows 平台创建进程时隐藏控制台窗口
_CREATION_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
)


class AdbError(Exception):
    """ADB 命令执行过程中的不可恢复错误。"""


class AdbExecutor:
    """ADB shell 命令执行器。

    封装对 adb.exe 的调用，提供类型安全的接口。
    每次调用创建独立子进程，无状态，线程安全。

    Args:
        adb_path: adb 可执行文件的绝对路径
        serial: 设备序列号（对应 adb -s 参数），None 则使用默认设备
    """

    def __init__(
        self,
        adb_path: Path,
        serial: str | None = None,
    ) -> None:
        self._adb_path = self._validate_adb_path(adb_path)
        self._serial = serial

    @staticmethod
    def _validate_adb_path(adb_path: Path) -> Path:
        """验证 adb 可执行文件路径。

        Args:
            adb_path: 待验证的 adb 路径

        Returns:
            解析后的绝对路径

        Raises:
            AdbError: 文件不存在或不可执行
        """
        resolved = adb_path.resolve()
        if not resolved.is_file():
            raise AdbError(f"adb 可执行文件不存在：{resolved}")
        return resolved

    def _build_command(self, *args: str) -> list[str]:
        """构建完整的 adb 命令行参数列表。

        Args:
            *args: adb 子命令及其参数

        Returns:
            完整的命令行参数列表（如 ["adb", "-s", "SERIAL", "shell", "ls"]）
        """
        cmd: list[str] = [str(self._adb_path)]
        if self._serial is not None:
            cmd.extend(["-s", self._serial])
        cmd.extend(args)
        return cmd

    def shell(
        self,
        command: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """执行 adb shell 命令。

        严格遵循 Python subprocess.run() 官方最佳实践：
        - 参数列表传递，不使用 shell=True
        - capture_output=True 捕获 stdout/stderr
        - text=True 自动解码为字符串
        - timeout 防止无限等待

        Args:
            command: shell 命令字符串（如 "ls /system/etc/mi"）
            timeout: 超时秒数，默认 30 秒

        Returns:
            CommandResult 包含命令输出和返回码

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        full_cmd = self._build_command("shell", command)
        logger.debug("执行: %s", " ".join(full_cmd))

        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_CREATION_FLAGS,
            )
        except FileNotFoundError as exc:
            raise AdbError(f"找不到 adb 可执行文件：{self._adb_path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(
                f"命令超时（{timeout}s）：{command}"
            ) from exc

        result = CommandResult(
            command=command,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            returncode=proc.returncode,
        )

        logger.debug(
            "结果: returncode=%d stdout=%r stderr=%r",
            result.returncode,
            result.stdout[:100],
            result.stderr[:100],
        )

        return result


def list_devices(
    adb_path: Path,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[DeviceInfo, ...]:
    """列出所有已连接的 ADB 设备。

    等价于执行 `adb devices` 并解析输出。
    这是一个模块级函数，不需要设备序列号。

    Args:
        adb_path: adb 可执行文件路径
        timeout: 超时秒数

    Returns:
        已连接设备信息的不可变元组

    Raises:
        AdbError: adb 不存在或执行失败
    """
    resolved = adb_path.resolve()
    if not resolved.is_file():
        raise AdbError(f"adb 可执行文件不存在：{resolved}")

    cmd = [str(resolved), "devices"]
    logger.debug("执行: %s", " ".join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATION_FLAGS,
        )
    except FileNotFoundError as exc:
        raise AdbError(f"找不到 adb 可执行文件：{resolved}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb devices 超时（{timeout}s）") from exc

    if proc.returncode != 0:
        raise AdbError(
            f"adb devices 失败（returncode={proc.returncode}）：{proc.stderr.strip()}"
        )

    return _parse_devices_output(proc.stdout)


def _parse_devices_output(output: str) -> tuple[DeviceInfo, ...]:
    """解析 adb devices 的输出。

    输出格式：
        List of devices attached
        SERIAL1\\tdevice
        SERIAL2\\toffline

    Args:
        output: adb devices 的标准输出

    Returns:
        解析后的设备信息元组
    """
    devices: list[DeviceInfo] = []
    for line in output.splitlines():
        stripped = line.strip()
        # 跳过标题行和空行
        if not stripped or stripped.startswith("List of devices"):
            continue
        parts = stripped.split("\t")
        if len(parts) >= 2:
            devices.append(DeviceInfo(serial=parts[0], state=parts[1]))
    return tuple(devices)

