"""
ADB 命令执行器 — 通用共享模块。

封装 subprocess.run() 调用 adb，遵循 Python 官方推荐的最佳实践：
- 使用参数列表而非字符串（避免 shell 注入）
- 不使用 shell=True
- 使用 capture_output=True + encoding="utf-8" 捕获输出
  （ADB 输出始终为 UTF-8，Windows 默认 locale 编码会导致 UnicodeDecodeError）
- 使用 errors="replace" 容错处理无法解码的字节
- 使用 timeout 防止挂起
- 对非零返回码不抛异常（shell 命令返回非零可能是正常业务逻辑）

由各功能模块（install-magisk、install-modules 等）共享。

参考：
- https://docs.python.org/3/library/subprocess.html#subprocess.run
- https://docs.python.org/3/library/subprocess.html#security-considerations
- https://docs.python.org/3/library/subprocess.html#frequently-used-arguments
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from .models import CommandResult, DeviceInfo

logger = logging.getLogger(__name__)

# ADB 命令执行的默认超时（秒）
_DEFAULT_TIMEOUT: float = 30.0

# 文件推送超时（秒）— 大文件 USB 传输需要较长时间
_PUSH_TIMEOUT: float = 300.0

# 等待设备超时（秒）— 设备重启可能需要较长时间
_WAIT_DEVICE_TIMEOUT: float = 120.0

# 重启后设备就绪的轮询间隔（秒）
_POLL_INTERVAL: float = 2.0

# Windows 平台创建进程时隐藏控制台窗口
_CREATION_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
)


class AdbError(Exception):
    """ADB 命令执行过程中的不可恢复错误。"""


class AdbExecutor:
    """ADB 命令执行器。

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

        遵循 Python 官方安全建议：使用参数列表而非字符串拼接。

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

    def _run(
        self,
        *args: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """执行 adb 命令并返回结果。

        所有公共方法的底层实现，统一处理：
        - subprocess.run() 调用
        - 异常捕获（FileNotFoundError / TimeoutExpired）
        - 结果封装

        Args:
            *args: adb 子命令及其参数
            timeout: 超时秒数

        Returns:
            CommandResult 包含命令输出和返回码

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        full_cmd = self._build_command(*args)
        cmd_str = " ".join(full_cmd)
        logger.debug("执行: %s", cmd_str)

        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=_CREATION_FLAGS,
            )
        except FileNotFoundError as exc:
            raise AdbError(
                f"找不到 adb 可执行文件：{self._adb_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(
                f"命令超时（{timeout}s）：{cmd_str}"
            ) from exc

        result = CommandResult(
            command=cmd_str,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            returncode=proc.returncode,
        )

        logger.debug(
            "结果: returncode=%d stdout=%r stderr=%r",
            result.returncode,
            result.stdout[:200],
            result.stderr[:200],
        )

        return result

    # ------------------------------------------------------------------
    # 基础 ADB 命令
    # ------------------------------------------------------------------

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
            command: shell 命令字符串（如 "twrp --version"）
            timeout: 超时秒数，默认 30 秒

        Returns:
            CommandResult 包含命令输出和返回码

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        return self._run("shell", command, timeout=timeout)

    def shell_su(
        self,
        command: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """以 root 权限执行 adb shell 命令。

        对应 pcapng 中的 shell:su -c "..." 格式。
        通过 su -c 包装命令实现 root 执行。

        Args:
            command: 要以 root 执行的命令（不含 su -c 前缀）
            timeout: 超时秒数

        Returns:
            CommandResult 包含命令输出和返回码

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        wrapped = f'su -c "{command}"'
        return self._run("shell", wrapped, timeout=timeout)

    def reboot(
        self,
        target: str = "",
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """重启设备。

        对应 pcapng 中的 OPEN reboot:recovery 和 OPEN reboot: 命令。

        Args:
            target: 重启目标（"recovery" / "" 表示正常重启）
            timeout: 超时秒数

        Returns:
            CommandResult

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        args = ["reboot"]
        if target:
            args.append(target)

        logger.info("重启设备: target=%s", target or "(normal)")
        return self._run(*args, timeout=timeout)

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    def push(
        self,
        local_path: Path,
        remote_path: str,
        *,
        timeout: float = _PUSH_TIMEOUT,
    ) -> CommandResult:
        """推送文件到设备。

        对应 pcapng 中 sync: → SEND 的 ADB SYNC 协议文件传输。
        adb push 命令内部使用相同的 SYNC 协议。

        Args:
            local_path: 本地文件路径
            remote_path: 设备端目标路径（如 "/sdcard/Magisk.zip"）
            timeout: 超时秒数，默认 300 秒（大文件传输）

        Returns:
            CommandResult

        Raises:
            AdbError: 文件不存在、adb 进程启动失败或超时
        """
        resolved_local = local_path.resolve()
        if not resolved_local.is_file():
            raise AdbError(f"本地文件不存在：{resolved_local}")

        logger.info(
            "推送文件: %s → %s (%.1f MB)",
            resolved_local.name,
            remote_path,
            resolved_local.stat().st_size / (1024 * 1024),
        )
        return self._run(
            "push", str(resolved_local), remote_path,
            timeout=timeout,
        )

    def push_directory(
        self,
        local_dir: Path,
        remote_dir: str,
        *,
        timeout: float = _PUSH_TIMEOUT,
    ) -> CommandResult:
        """推送整个目录到设备。

        对应 pcapng 中的 sync: → STA2 + SND2 批量文件传输。
        adb push 支持目录推送，内部使用 SYNC 协议的同一会话传输所有文件。

        Args:
            local_dir: 本地目录路径
            remote_dir: 设备端目标目录路径（如 "/sdcard/modules"）
            timeout: 超时秒数

        Returns:
            CommandResult

        Raises:
            AdbError: 目录不存在、adb 进程启动失败或超时
        """
        resolved_dir = local_dir.resolve()
        if not resolved_dir.is_dir():
            raise AdbError(f"本地目录不存在：{resolved_dir}")

        file_count = sum(1 for f in resolved_dir.iterdir() if f.is_file())
        total_size = sum(
            f.stat().st_size
            for f in resolved_dir.iterdir()
            if f.is_file()
        )

        logger.info(
            "推送目录: %s → %s (%d 文件, %.1f MB)",
            resolved_dir.name,
            remote_dir,
            file_count,
            total_size / (1024 * 1024),
        )
        return self._run(
            "push", str(resolved_dir) + "/", remote_dir + "/",
            timeout=timeout,
        )

    def pull(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout: float = _PUSH_TIMEOUT,
    ) -> CommandResult:
        """从设备拉取文件到本地。

        对应 pcapng 中 sync: → RECV 的 ADB SYNC 协议文件传输。
        adb pull 命令内部使用相同的 SYNC 协议。

        Args:
            remote_path: 设备端源文件路径（如 "/data/system/packages.xml"）
            local_path: 本地保存路径
            timeout: 超时秒数，默认 300 秒（大文件传输）

        Returns:
            CommandResult

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        resolved_local = local_path.resolve()
        resolved_local.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "拉取文件: %s → %s",
            remote_path,
            resolved_local,
        )
        return self._run(
            "pull", remote_path, str(resolved_local),
            timeout=timeout,
        )

    def file_exists(
        self,
        remote_path: str,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """检查设备上文件是否存在。

        使用 `ls` 命令探测，适用于验证 push 是否成功。

        Args:
            remote_path: 设备端文件路径
            timeout: 超时秒数

        Returns:
            True 如果文件存在
        """
        result = self.shell(
            f"ls {remote_path}",
            timeout=timeout,
        )
        exists = result.success and "No such file" not in result.output
        logger.debug(
            "文件检查 %s: %s",
            remote_path,
            "存在" if exists else "不存在",
        )
        return exists

    # ------------------------------------------------------------------
    # APK 安装
    # ------------------------------------------------------------------

    def install_apk(
        self,
        apk_path: Path,
        *,
        replace: bool = True,
        downgrade: bool = True,
        test: bool = True,
        user: int = 0,
        timeout: float = _PUSH_TIMEOUT,
    ) -> CommandResult:
        """安装单个 APK 文件。

        等效于 adb install -r -d -t --user 0 <apk>。

        Args:
            apk_path: APK 文件路径
            replace: 是否允许覆盖安装（-r）
            downgrade: 是否允许降级安装（-d）
            test: 是否允许测试包（-t）
            user: 安装目标用户 ID（--user）
            timeout: 超时秒数

        Returns:
            CommandResult

        Raises:
            AdbError: APK 文件不存在、adb 进程启动失败或超时
        """
        resolved = apk_path.resolve()
        if not resolved.is_file():
            raise AdbError(f"APK 文件不存在：{resolved}")

        args: list[str] = ["install"]
        if replace:
            args.append("-r")
        if downgrade:
            args.append("-d")
        if test:
            args.append("-t")
        args.extend(["--user", str(user)])
        args.append(str(resolved))

        size_mb = resolved.stat().st_size / (1024 * 1024)
        logger.info(
            "安装 APK: %s (%.1f MB)", resolved.name, size_mb,
        )

        return self._run(*args, timeout=timeout)

    def install_multiple(
        self,
        apk_paths: tuple[Path, ...],
        *,
        replace: bool = True,
        downgrade: bool = True,
        test: bool = True,
        user: int = 0,
        timeout: float = _PUSH_TIMEOUT,
    ) -> CommandResult:
        """安装多个分割 APK（split APKs）。

        对应 pcapng 中的 exec:cmd package 'install-create/write/commit' 流程。
        adb install-multiple 命令内部自动执行：
        1. install-create -r -d -t --user 0 → 创建安装会话
        2. install-write -S {size} {session} {name}.apk × N → 流式写入每个 APK
        3. install-commit {session} → 提交安装

        参数 -r -d -t --user 0 与 pcapng 中观察到的参数完全一致：
        - -r: replace existing application (允许覆盖安装)
        - -d: allow version code downgrade (允许降级)
        - -t: allow test packages (允许测试包)
        - --user 0: install for user 0 (主用户)

        Args:
            apk_paths: 分割 APK 文件路径元组（base APK 在第一个）
            replace: 是否允许覆盖安装（-r）
            downgrade: 是否允许降级安装（-d）
            test: 是否允许测试包（-t）
            user: 安装目标用户 ID（--user）
            timeout: 超时秒数（大文件传输 + 安装需要较长时间）

        Returns:
            CommandResult

        Raises:
            AdbError: APK 文件不存在、adb 进程启动失败或超时
        """
        # 验证所有 APK 文件存在
        for apk_path in apk_paths:
            resolved = apk_path.resolve()
            if not resolved.is_file():
                raise AdbError(f"APK 文件不存在：{resolved}")

        # 构建命令参数（参数列表形式，遵循 subprocess 安全最佳实践）
        args: list[str] = ["install-multiple"]
        if replace:
            args.append("-r")
        if downgrade:
            args.append("-d")
        if test:
            args.append("-t")
        args.extend(["--user", str(user)])

        # 添加所有 APK 路径
        for apk_path in apk_paths:
            args.append(str(apk_path.resolve()))

        total_size = sum(
            p.resolve().stat().st_size for p in apk_paths
        )
        logger.info(
            "安装 %d 个 split APK (%.1f MB)",
            len(apk_paths),
            total_size / (1024 * 1024),
        )

        return self._run(*args, timeout=timeout)

    def pm_enable(
        self,
        package_name: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CommandResult:
        """启用 Android 包。

        对应 pcapng 中的 shell,v2,raw:pm enable {package_name}。

        Args:
            package_name: Android 包名（如 "com.android.vending"）
            timeout: 超时秒数

        Returns:
            CommandResult

        Raises:
            AdbError: adb 进程启动失败或超时
        """
        logger.info("启用包: %s", package_name)
        return self.shell(
            f"pm enable {package_name}",
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # 等待设备就绪
    # ------------------------------------------------------------------

    def wait_for_device(
        self,
        state: str = "device",
        *,
        timeout: float = _WAIT_DEVICE_TIMEOUT,
    ) -> CommandResult:
        """等待设备进入指定状态。

        使用 adb wait-for-{state} 命令，这是 ADB 官方推荐的
        等待设备就绪的方式。

        Args:
            state: 目标状态（"device" / "recovery" / "bootloader"）
            timeout: 超时秒数，默认 120 秒

        Returns:
            CommandResult

        Raises:
            AdbError: 超时未等到设备
        """
        wait_arg = f"wait-for-{state}"
        logger.info("等待设备状态: %s (timeout=%ds)", state, int(timeout))
        return self._run(wait_arg, timeout=timeout)

    def wait_for_shell_ready(
        self,
        *,
        probe_command: str = "echo ready",
        timeout: float = _WAIT_DEVICE_TIMEOUT,
        poll_interval: float = _POLL_INTERVAL,
    ) -> bool:
        """等待设备 shell 完全就绪。

        adb wait-for-device 仅等待 USB 连接建立，
        不保证 shell 服务已准备好接受命令。
        此方法通过轮询 shell 命令来确认就绪状态。

        Args:
            probe_command: 探测命令（默认 "echo ready"）
            timeout: 总超时秒数
            poll_interval: 轮询间隔秒数

        Returns:
            True 如果 shell 已就绪，False 如果超时
        """
        deadline = time.monotonic() + timeout
        attempt = 0

        while time.monotonic() < deadline:
            attempt += 1
            try:
                result = self.shell(
                    probe_command,
                    timeout=min(5.0, deadline - time.monotonic()),
                )
                if result.success:
                    logger.info(
                        "Shell 就绪（第 %d 次尝试）", attempt
                    )
                    return True
            except AdbError:
                pass

            remaining = deadline - time.monotonic()
            if remaining > 0:
                sleep_time = min(poll_interval, remaining)
                logger.debug(
                    "Shell 未就绪，%ds 后重试（第 %d 次）",
                    int(sleep_time), attempt,
                )
                time.sleep(sleep_time)

        logger.warning("等待 shell 就绪超时（%ds）", int(timeout))
        return False

    def wait_for_twrp_ready(
        self,
        *,
        timeout: float = _WAIT_DEVICE_TIMEOUT,
        poll_interval: float = _POLL_INTERVAL,
    ) -> bool:
        """等待 TWRP Recovery 守护进程完全就绪。

        adb shell 可用 ≠ TWRP daemon 就绪。
        `twrp --version` 是静态命令，不依赖 daemon；
        但 `twrp install` 等操作需要 TWRP daemon 运行。

        此方法通过轮询 `twrp listmounts`（需要 daemon）来确认就绪，
        同时验证 /sdcard 存储已挂载（确保 push 的文件可被访问）。

        Args:
            timeout: 总超时秒数
            poll_interval: 轮询间隔秒数

        Returns:
            True 如果 TWRP daemon 和存储都已就绪，False 如果超时
        """
        deadline = time.monotonic() + timeout
        attempt = 0

        while time.monotonic() < deadline:
            attempt += 1
            try:
                # twrp listmounts 需要 TWRP daemon 运行
                # 如果 daemon 未就绪会输出 "TWRP does not appear to be running"
                result = self.shell(
                    "twrp listmounts",
                    timeout=min(10.0, max(1.0, deadline - time.monotonic())),
                )

                output = result.output.lower()

                # 检查 daemon 是否报告未运行
                if "does not appear to be running" in output:
                    logger.debug(
                        "TWRP daemon 未就绪（第 %d 次）", attempt
                    )
                else:
                    # daemon 就绪，再检查 /sdcard 是否可访问
                    storage_result = self.shell(
                        "ls /sdcard/",
                        timeout=5.0,
                    )
                    if storage_result.success:
                        logger.info(
                            "TWRP daemon + 存储就绪（第 %d 次尝试）",
                            attempt,
                        )
                        return True
                    logger.debug(
                        "/sdcard/ 未就绪（第 %d 次）: %s",
                        attempt, storage_result.output[:100],
                    )

            except AdbError:
                logger.debug(
                    "TWRP 就绪探测异常（第 %d 次）", attempt
                )

            remaining = deadline - time.monotonic()
            if remaining > 0:
                sleep_time = min(poll_interval, remaining)
                time.sleep(sleep_time)

        logger.warning(
            "等待 TWRP daemon 就绪超时（%ds）", int(timeout)
        )
        return False


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
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATION_FLAGS,
        )
    except FileNotFoundError as exc:
        raise AdbError(f"找不到 adb 可执行文件：{resolved}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb devices 超时（{timeout}s）") from exc

    if proc.returncode != 0:
        raise AdbError(
            f"adb devices 失败（returncode={proc.returncode}）："
            f"{proc.stderr.strip()}"
        )

    return _parse_devices_output(proc.stdout)


def _parse_devices_output(output: str) -> tuple[DeviceInfo, ...]:
    """解析 adb devices 的输出。

    输出格式：
        List of devices attached
        SERIAL1\\tdevice
        SERIAL2\\trecovery

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
