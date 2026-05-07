"""
ADB 命令执行客户端。

通过 subprocess 调用本地 adb 可执行文件，封装 shell 命令执行、
超时控制和异常处理。

用法::

    from adb_client import AdbClient

    client = AdbClient()                         # 自动定位 adb
    client = AdbClient(serial="SERIAL_NUMBER")   # 指定设备

    result = client.shell("getprop ro.product.brand")
    print(result.output)   # "google"
    print(result.success)  # True
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 默认命令超时（秒）
DEFAULT_TIMEOUT: int = 30

#: adb 可执行文件名（Windows 平台）
_ADB_EXECUTABLE: str = "adb.exe" if os.name == "nt" else "adb"


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AdbResult:
    """单条 ADB 命令的执行结果。

    Attributes:
        command: 完整命令行参数列表。
        return_code: 进程返回码。
        stdout: 标准输出（已解码并去除尾部空白）。
        stderr: 标准错误（已解码并去除尾部空白）。
    """

    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        """命令是否执行成功（返回码为 0）。"""
        return self.return_code == 0

    @property
    def output(self) -> str:
        """返回 stdout（去除尾部换行），便于快速获取结果。"""
        return (self.stdout or "").strip()


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class AdbError(Exception):
    """ADB 命令执行异常基类。"""


class AdbNotFoundError(AdbError):
    """找不到 adb 可执行文件。"""


class AdbTimeoutError(AdbError):
    """ADB 命令执行超时。"""


class AdbCommandError(AdbError):
    """ADB 命令执行失败（非零返回码）。

    Attributes:
        result: 失败的命令结果。
    """

    def __init__(self, message: str, result: AdbResult) -> None:
        super().__init__(message)
        self.result = result


# ---------------------------------------------------------------------------
# ADB 客户端
# ---------------------------------------------------------------------------

class AdbClient:
    """ADB 命令执行客户端。

    参数：
        adb_path: adb 可执行文件路径。为 None 时自动查找。
        serial: 设备序列号。为 None 时使用默认设备。
        timeout: 默认命令超时（秒）。

    Raises:
        AdbNotFoundError: 找不到 adb 可执行文件。
    """

    def __init__(
        self,
        adb_path: str | Path | None = None,
        serial: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._adb_path: Path = self._resolve_adb_path(adb_path)
        self._serial: str | None = serial
        self._timeout: int = timeout

        logger.debug(
            "AdbClient 初始化: adb=%s, serial=%s, timeout=%d",
            self._adb_path, self._serial, self._timeout,
        )

    # -- 公开属性 --

    @property
    def adb_path(self) -> Path:
        """adb 可执行文件路径。"""
        return self._adb_path

    @property
    def serial(self) -> str | None:
        """设备序列号。"""
        return self._serial

    # -- 核心方法 --

    def devices(self) -> list[dict[str, str]]:
        """执行 ``adb devices -l``，列出所有已连接设备。

        ADB 官方文档推荐使用 ``adb devices`` 获取设备列表。
        ``-l`` 参数附加设备详细信息（型号、传输方式等）。

        返回：
            设备信息字典列表，每项包含：
            - ``serial``: 设备序列号
            - ``state``: 设备状态（``device`` / ``offline`` / ``unauthorized``）
            - ``info``: 附加信息字符串

        注意：此方法不使用 ``-s`` 参数，始终列出所有设备。
        """
        cmd = [str(self._adb_path), "devices", "-l"]
        logger.debug("列出设备: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._timeout,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            ),
        )

        result: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            # 跳过标题行 "List of devices attached" 和空行
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                result.append({
                    "serial": parts[0],
                    "state": parts[1],
                    "info": parts[2] if len(parts) > 2 else "",
                })

        return result

    def shell(
        self,
        command: str,
        *,
        timeout: int | None = None,
        check: bool = False,
    ) -> AdbResult:
        """执行 ``adb shell <command>``。

        参数：
            command: 要在设备上执行的 shell 命令。
            timeout: 命令超时（秒）。为 None 时使用实例默认值。
            check: 为 True 时，命令失败则抛出 AdbCommandError。

        返回：
            AdbResult 对象。

        Raises:
            AdbTimeoutError: 命令超时。
            AdbCommandError: check=True 且命令失败。
        """
        return self.run("shell", command, timeout=timeout, check=check)

    def push(
        self,
        local_path: str | Path,
        remote_path: str,
        *,
        timeout: int | None = None,
        check: bool = False,
    ) -> AdbResult:
        """执行 ``adb push <local> <remote>``。

        对应抓包中的 sync 协议（STA2 → SND2 → DATA → OKAY/QUIT）。

        参数：
            local_path: 本地文件路径。
            remote_path: 设备端目标路径。
            timeout: 命令超时（秒）。为 None 时使用实例默认值。
            check: 为 True 时，命令失败则抛出 AdbCommandError。

        返回：
            AdbResult 对象。

        Raises:
            FileNotFoundError: 本地文件不存在。
            AdbTimeoutError: 命令超时。
            AdbCommandError: check=True 且命令失败。
        """
        local = Path(local_path)
        if not local.is_file():
            raise FileNotFoundError(f"本地文件不存在: {local}")

        logger.info("推送文件: %s → %s", local, remote_path)
        # push 大文件可能耗时较长，使用更宽松的超时
        effective_timeout = timeout if timeout is not None else max(self._timeout, 120)
        return self.run(
            "push", str(local), remote_path,
            timeout=effective_timeout, check=check,
        )

    def push_dir(
        self,
        local_dir: str | Path,
        remote_dir: str,
        *,
        timeout: int | None = None,
        check: bool = False,
    ) -> AdbResult:
        """执行 ``adb push <local_dir>/. <remote_dir>``，推送整个目录。

        对应抓包中的 sync 协议批量传输序列。
        ``adb push`` 原生支持目录推送，会递归推送所有文件。

        参数：
            local_dir: 本地目录路径。
            remote_dir: 设备端目标目录路径。
            timeout: 命令超时（秒）。为 None 时使用实例默认值。
            check: 为 True 时，命令失败则抛出 AdbCommandError。

        返回：
            AdbResult 对象。

        Raises:
            FileNotFoundError: 本地目录不存在。
            AdbTimeoutError: 命令超时。
            AdbCommandError: check=True 且命令失败。
        """
        local = Path(local_dir)
        if not local.is_dir():
            raise FileNotFoundError(f"本地目录不存在: {local}")

        logger.info("推送目录: %s → %s", local, remote_dir)
        # 目录推送可能包含多个大文件，使用更宽松的超时
        effective_timeout = timeout if timeout is not None else max(self._timeout, 300)
        return self.run(
            "push", str(local) + "/.", remote_dir,
            timeout=effective_timeout, check=check,
        )

    def reboot(
        self,
        target: str = "",
        *,
        timeout: int | None = None,
    ) -> AdbResult:
        """执行 ``adb reboot [target]``。

        对应抓包中的 ``reboot:recovery`` 和 ``reboot:`` 命令。

        参数：
            target: 重启目标。空字符串表示正常重启，
                ``"recovery"`` 进入 Recovery，``"bootloader"`` 进入 Bootloader。
            timeout: 命令超时（秒）。为 None 时使用实例默认值。

        返回：
            AdbResult 对象。
        """
        args: tuple[str, ...] = ("reboot", target) if target else ("reboot",)
        logger.info("重启设备: target=%r", target or "(normal)")
        return self.run(*args, timeout=timeout)

    def wait_for_device(
        self,
        state: str = "device",
        *,
        timeout: int = 60,
    ) -> AdbResult:
        """执行 ``adb wait-for-<state>``，阻塞直到设备就绪。

        参数：
            state: 等待的设备状态，可选值：
                ``"device"``、``"recovery"``、``"sideload"``、``"bootloader"``。
            timeout: 等待超时（秒），默认 60 秒。

        返回：
            AdbResult 对象。

        Raises:
            AdbTimeoutError: 等待超时。
        """
        logger.info("等待设备状态: %s (timeout=%ds)", state, timeout)
        return self.run(f"wait-for-{state}", timeout=timeout)

    def run(
        self,
        *args: str,
        timeout: int | None = None,
        check: bool = False,
    ) -> AdbResult:
        """执行任意 adb 命令。

        参数：
            *args: adb 子命令及参数（例如 ``"shell", "ls /data"``）。
            timeout: 命令超时（秒）。为 None 时使用实例默认值。
            check: 为 True 时，命令失败则抛出 AdbCommandError。

        返回：
            AdbResult 对象。

        Raises:
            AdbTimeoutError: 命令超时。
            AdbCommandError: check=True 且命令失败。
        """
        cmd = self._build_command(args)
        effective_timeout = timeout if timeout is not None else self._timeout

        logger.debug("执行: %s (timeout=%ds)", " ".join(cmd), effective_timeout)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"命令超时 ({effective_timeout}s): {' '.join(cmd)}"
            logger.error(msg)
            raise AdbTimeoutError(msg) from exc

        result = AdbResult(
            command=tuple(cmd),
            return_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

        if result.success:
            logger.debug("成功: rc=%d, stdout=%r", result.return_code, result.output)
        else:
            logger.warning(
                "失败: rc=%d, stderr=%r", result.return_code, result.stderr.strip(),
            )

        if check and not result.success:
            msg = (
                f"命令失败 (rc={result.return_code}): {' '.join(cmd)}"
                f"\nstderr: {result.stderr.strip()}"
            )
            raise AdbCommandError(msg, result)

        return result

    # -- 私有方法 --

    def _build_command(self, args: Sequence[str]) -> list[str]:
        """构建完整的 adb 命令行。"""
        cmd: list[str] = [str(self._adb_path)]
        if self._serial:
            cmd.extend(["-s", self._serial])
        cmd.extend(args)
        return cmd

    @staticmethod
    def _resolve_adb_path(adb_path: str | Path | None) -> Path:
        """解析 adb 可执行文件路径。

        查找顺序：
        1. 明确指定的路径
        2. 脚本同级 platform-tools 目录
        3. 系统 PATH
        """
        # 1. 明确指定
        if adb_path is not None:
            path = Path(adb_path)
            if path.is_file():
                return path
            raise AdbNotFoundError(f"指定的 adb 路径不存在: {path}")

        # 2. 同级 platform-tools 目录
        script_dir = Path(__file__).resolve().parent
        platform_tools_adb = script_dir / "platform-tools" / _ADB_EXECUTABLE
        if platform_tools_adb.is_file():
            return platform_tools_adb

        # 3. 系统 PATH
        import shutil
        system_adb = shutil.which(_ADB_EXECUTABLE)
        if system_adb is not None:
            return Path(system_adb)

        raise AdbNotFoundError(
            f"找不到 adb 可执行文件。"
            f"尝试过的路径: {platform_tools_adb}, 以及系统 PATH"
        )
