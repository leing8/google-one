"""
Install Magisk & Root Phone — 通过 TWRP Recovery 安装 Magisk 并 Root 设备。

基于 Wireshark 抓包 ``5.0-Install Magisk && Root Phone.txt`` 逐行解析，
严格按照抓包中的命令顺序和返回值判断逻辑实现。

抓包命令完整序列::

    1. adb reboot recovery          — 重启进入 Recovery
    2. (wait-for-recovery)          — 等待设备就绪
    3. adb shell twrp --version     — TWRP 前置条件检查
    4. adb push Magisk.zip /sdcard/ — 推送安装包（sync 协议）
    5. adb shell twrp install ...   — 通过 TWRP 安装 Magisk
    6. adb shell rm -rf ...         — 清理安装包
    7. adb reboot                   — 重启设备

命令行用法::

    python install_magisk.py
    python install_magisk.py --serial SERIAL_NUMBER
    python install_magisk.py --magisk-zip /path/to/Magisk.zip

模块用法::

    from install_magisk import MagiskInstaller
    from adb_client import AdbClient

    client = AdbClient(serial="SERIAL_NUMBER")
    installer = MagiskInstaller(client)
    result = installer.install()
    print(result)
"""

from __future__ import annotations

import argparse
import enum
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adb_client import AdbClient, AdbError, AdbTimeoutError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 设备端 Magisk.zip 存放路径（与抓包一致）
_REMOTE_MAGISK_PATH: str = "/sdcard/Magisk.zip"

#: 默认本地 Magisk.zip 路径（项目根目录）
_DEFAULT_LOCAL_MAGISK: Path = Path(__file__).resolve().parent / "Magisk.zip"

#: 等待 Recovery 超时（秒）
_RECOVERY_WAIT_TIMEOUT: int = 60

#: TWRP 安装命令超时（秒）——安装过程较慢
_INSTALL_TIMEOUT: int = 300

#: TWRP 完全就绪等待超时（秒）
#: 包含 ro.twrp.boot 属性出现 + TWRP GUI 初始化 + 存储挂载
_TWRP_READY_TIMEOUT: int = 60

#: TWRP 就绪轮询间隔（秒）
_TWRP_READY_POLL_INTERVAL: int = 2


# ---------------------------------------------------------------------------
# 枚举与数据类
# ---------------------------------------------------------------------------

class StepStatus(enum.Enum):
    """单步骤执行状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """单步骤执行结果。

    Attributes:
        name: 步骤名称。
        status: 执行状态。
        message: 结果描述。
        output: 命令原始输出（可选）。
    """

    name: str
    status: StepStatus
    message: str
    output: str = ""


@dataclass
class MagiskInstallResult:
    """Magisk 安装流程整体结果。

    Attributes:
        success: 安装是否成功。
        twrp_version: 检测到的 TWRP 版本字符串。
        install_log: TWRP 安装过程的完整日志。
        steps: 各步骤执行结果列表。
        error: 失败时的错误信息。
    """

    success: bool = False
    twrp_version: str = ""
    install_log: str = ""
    steps: list[StepResult] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "success": self.success,
            "twrp_version": self.twrp_version,
            "install_log": self.install_log,
            "steps": [
                {"name": s.name, "status": s.status.value, "message": s.message}
                for s in self.steps
            ],
            "error": self.error,
        }

    def __str__(self) -> str:
        """人类可读的结果摘要。"""
        status_icon = "[OK]" if self.success else "[FAIL]"
        lines = [
            "=" * 60,
            f"  {status_icon}  Magisk Installation Result",
            "=" * 60,
            f"  TWRP Version:  {self.twrp_version or 'N/A'}",
            f"  Overall:       {'SUCCESS' if self.success else 'FAILED'}",
        ]
        if self.error:
            lines.append(f"  Error:         {self.error}")
        lines.append("-" * 60)
        for step in self.steps:
            icon = {"success": "+", "failed": "X", "skipped": "o"}[step.status.value]
            lines.append(f"  [{icon}] {step.name}: {step.message}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 安装器
# ---------------------------------------------------------------------------

class MagiskInstaller:
    """按 Wireshark 抓包流程安装 Magisk。

    严格按照 ``5.0-Install Magisk && Root Phone.txt`` 中记录的
    命令顺序和返回值判断逻辑执行，每一步根据返回值决定是否继续。

    参数：
        adb: AdbClient 实例。
        magisk_zip: 本地 Magisk.zip 文件路径。
    """

    def __init__(
        self,
        adb: AdbClient,
        magisk_zip: str | Path = _DEFAULT_LOCAL_MAGISK,
    ) -> None:
        self._adb = adb
        self._magisk_zip = Path(magisk_zip)

    def install(self) -> MagiskInstallResult:
        """执行完整的 Magisk 安装流程。

        按抓包顺序依次执行：

        1. ``adb reboot recovery``              — 重启到 Recovery
        2. ``adb wait-for-recovery``            — 等待设备就绪
        3. ``adb shell twrp --version``         — TWRP 前置条件检查
        4. ``adb push Magisk.zip /sdcard/``     — 推送安装包
        5. ``adb shell twrp install ...``       — 安装 Magisk
        6. ``adb shell rm -rf /sdcard/Magisk.zip`` — 清理
        7. ``adb reboot``                       — 重启设备

        每一步都根据返回值判断是否继续下一步。
        即使安装失败，也会尝试清理和重启，避免设备滞留在 Recovery。

        返回：
            MagiskInstallResult 对象。
        """
        result = MagiskInstallResult()

        # -- 前置检查：本地 Magisk.zip 是否存在 --
        if not self._magisk_zip.is_file():
            result.error = f"本地 Magisk.zip 不存在: {self._magisk_zip}"
            result.steps.append(StepResult(
                name="检查本地文件",
                status=StepStatus.FAILED,
                message=result.error,
            ))
            logger.error(result.error)
            return result

        result.steps.append(StepResult(
            name="检查本地文件",
            status=StepStatus.SUCCESS,
            message=f"找到 {self._magisk_zip.name} "
                    f"({self._magisk_zip.stat().st_size / 1024 / 1024:.1f} MB)",
        ))

        # -- Step 1: adb reboot recovery（对应抓包 reboot:recovery）--
        step = self._reboot_to_recovery()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # -- Step 2: 等待 Recovery 就绪 --
        step = self._wait_for_recovery()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # -- Step 3: TWRP 前置条件检查（对应抓包 shell:twrp --version）--
        step, twrp_version = self._check_twrp()
        result.steps.append(step)
        result.twrp_version = twrp_version
        if step.status == StepStatus.FAILED:
            result.error = step.message
            # TWRP 不可用时尝试重启回正常模式
            self._safe_reboot(result)
            return result

        # -- Step 4: adb push（对应抓包 sync 协议）--
        step = self._push_magisk_zip()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            self._safe_cleanup(result)
            self._safe_reboot(result)
            return result

        # -- Step 5: twrp install（对应抓包 shell:twrp install）--
        step, install_log = self._install_magisk()
        result.steps.append(step)
        result.install_log = install_log
        install_success = step.status == StepStatus.SUCCESS
        if not install_success:
            result.error = step.message

        # -- Step 6: 清理（对应抓包 shell,v2:rm -rf）--
        # 无论安装是否成功，都执行清理
        self._safe_cleanup(result)

        # -- Step 7: 重启（对应抓包 reboot:）--
        # 无论安装是否成功，都执行重启
        self._safe_reboot(result)

        result.success = install_success
        return result

    # -- 私有方法：各步骤实现 --

    def _reboot_to_recovery(self) -> StepResult:
        """Step 1: 重启到 Recovery 模式。

        对应抓包命令 ``reboot:recovery``。

        注意：``adb reboot recovery`` 会导致 USB 断开，返回码可能非零，
        这是预期行为。真正的成功判断由 Step 2 ``wait-for-recovery`` 完成。
        """
        logger.info("Step 1: 重启到 Recovery (adb reboot recovery)")
        try:
            res = self._adb.reboot("recovery")
            # 返回码非零是预期的（USB 断开），仅记录日志
            if not res.success:
                logger.debug(
                    "reboot recovery 返回码 %d（USB 断开，属预期行为）",
                    res.return_code,
                )
        except AdbError as exc:
            # reboot 导致连接断开时可能抛异常，同样属于预期行为
            logger.debug("reboot recovery 异常（USB 断开，属预期行为）: %s", exc)

        return StepResult(
            name="重启到 Recovery",
            status=StepStatus.SUCCESS,
            message="已发送重启到 Recovery 命令",
        )

    def _wait_for_recovery(self) -> StepResult:
        """Step 2: 等待设备进入 Recovery 模式。

        对应抓包中设备重连后 CNXN 握手阶段。
        """
        logger.info(
            "Step 2: 等待 Recovery 就绪 (timeout=%ds)", _RECOVERY_WAIT_TIMEOUT,
        )
        try:
            res = self._adb.wait_for_device(
                "recovery", timeout=_RECOVERY_WAIT_TIMEOUT,
            )
        except AdbTimeoutError:
            return StepResult(
                name="等待 Recovery",
                status=StepStatus.FAILED,
                message=f"等待 Recovery 超时 ({_RECOVERY_WAIT_TIMEOUT}s)",
            )
        except AdbError as exc:
            return StepResult(
                name="等待 Recovery",
                status=StepStatus.FAILED,
                message=f"等待 Recovery 失败: {exc}",
            )

        return StepResult(
            name="等待 Recovery",
            status=StepStatus.SUCCESS,
            message="设备已进入 Recovery 模式",
        )

    def _check_twrp(self) -> tuple[StepResult, str]:
        """Step 3: 等待 TWRP 完全就绪并检查版本。

        对应抓包命令 ``shell:twrp --version``。

        基于 TWRP 官方源码（twrp.cpp / openrecoveryscript.cpp）的就绪机制：

        1. **ro.twrp.boot 属性** — TWRP 进程启动时在 ``main()`` 中设置
           ``property_set("ro.twrp.boot", "1")``，是官方的进程启动信号。
        2. **twrp get tw_storage_path** — 通过 FIFO 发送给 TWRP GUI，
           必须 GUI 完全初始化且存储挂载完成后才能响应。
        3. **twrp --version** — 获取版本号，此时必定成功。

        前置条件判断与抓包一致：输出包含 ``"TWRP"`` 关键字。

        返回：
            (StepResult, twrp_version_string) 元组。
        """
        logger.info("Step 3: 等待 TWRP 就绪并检查版本")

        # 阶段 1: 等待 ro.twrp.boot=1（TWRP 进程启动信号）
        if not self._wait_for_twrp_property():
            return (
                StepResult(
                    name="检查 TWRP",
                    status=StepStatus.FAILED,
                    message=f"TWRP 进程在 {_TWRP_READY_TIMEOUT}s 内未启动"
                            f"（ro.twrp.boot 未设置）",
                ),
                "",
            )

        # 阶段 2: 等待 TWRP GUI + 存储就绪（通过 FIFO 命令验证）
        if not self._wait_for_twrp_gui_ready():
            return (
                StepResult(
                    name="检查 TWRP",
                    status=StepStatus.FAILED,
                    message=f"TWRP GUI 在 {_TWRP_READY_TIMEOUT}s 内未就绪",
                ),
                "",
            )

        # 阶段 3: 获取版本（此时 TWRP 已完全就绪）
        try:
            res = self._adb.shell("twrp --version")
        except AdbError as exc:
            return (
                StepResult(
                    name="检查 TWRP",
                    status=StepStatus.FAILED,
                    message=f"获取 TWRP 版本失败: {exc}",
                ),
                "",
            )

        output = res.output
        if not res.success or "TWRP" not in output:
            return (
                StepResult(
                    name="检查 TWRP",
                    status=StepStatus.FAILED,
                    message=f"Recovery 非 TWRP，输出: {output!r}",
                    output=output,
                ),
                "",
            )

        twrp_version = self._parse_twrp_version(output)
        logger.info("TWRP 版本: %s", twrp_version or output)
        return (
            StepResult(
                name="检查 TWRP",
                status=StepStatus.SUCCESS,
                message=f"TWRP 版本: {twrp_version or output}",
                output=output,
            ),
            twrp_version or output,
        )

    def _wait_for_twrp_property(self) -> bool:
        """等待 TWRP 设置 ``ro.twrp.boot=1`` 属性。

        TWRP 源码 twrp.cpp:350::

            property_set("ro.twrp.boot", "1");

        此属性在 TWRP ``main()`` 启动时设置，是官方的进程启动信号。
        """
        deadline = time.monotonic() + _TWRP_READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                res = self._adb.shell("getprop ro.twrp.boot")
                if res.output.strip() == "1":
                    logger.info("ro.twrp.boot=1, TWRP 进程已启动")
                    return True
            except AdbError:
                pass
            time.sleep(_TWRP_READY_POLL_INTERVAL)
        logger.error("等待 ro.twrp.boot 超时")
        return False

    def _wait_for_twrp_gui_ready(self) -> bool:
        """等待 TWRP GUI 完全初始化并挂载存储。

        使用 ``twrp get tw_storage_path`` 验证 TWRP GUI 就绪：
        - 此命令通过 FIFO 发送给 TWRP GUI 进程（openrecoveryscript.cpp:670）
        - 必须 GUI 启动、监听 FIFO 且存储挂载完成后才能返回有效值
        - 成功响应表示 TWRP 已完全可用
        """
        deadline = time.monotonic() + _TWRP_READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                res = self._adb.shell("twrp get tw_storage_path")
                if res.success and "/" in res.output:
                    logger.info("TWRP GUI 已就绪, 存储路径: %s",
                                res.output.strip())
                    return True
            except AdbError:
                pass
            time.sleep(_TWRP_READY_POLL_INTERVAL)
        logger.error("等待 TWRP GUI 就绪超时")
        return False

    def _push_magisk_zip(self) -> StepResult:
        """Step 4: 推送 Magisk.zip 到设备。

        对应抓包中的 sync 协议序列：
        ``sync:`` → ``STA2 /sdcard/Magisk.zip`` → ``SND2`` → ``DATA`` → ``OKAY`` → ``QUIT``

        前置条件已由 ``_wait_for_twrp_gui_ready()`` 确保存储可用，
        因此单次推送+验证即可，无需重试。
        """
        logger.info(
            "Step 4: 推送 Magisk.zip (adb push %s %s)",
            self._magisk_zip, _REMOTE_MAGISK_PATH,
        )

        try:
            res = self._adb.push(self._magisk_zip, _REMOTE_MAGISK_PATH)
        except FileNotFoundError as exc:
            return StepResult(
                name="推送 Magisk.zip",
                status=StepStatus.FAILED,
                message=str(exc),
            )
        except AdbError as exc:
            return StepResult(
                name="推送 Magisk.zip",
                status=StepStatus.FAILED,
                message=f"推送异常: {exc}",
            )

        if not res.success:
            return StepResult(
                name="推送 Magisk.zip",
                status=StepStatus.FAILED,
                message=f"推送失败 (rc={res.return_code}): {res.stderr.strip()}",
            )

        # 防御性验证：确认文件存在于设备上
        verify = self._adb.shell(f"ls -l {_REMOTE_MAGISK_PATH}")
        if not verify.success or "No such file" in verify.output:
            return StepResult(
                name="推送 Magisk.zip",
                status=StepStatus.FAILED,
                message="推送命令成功但文件未出现在设备上",
            )

        logger.info("推送完成: %s", verify.output.strip())
        return StepResult(
            name="推送 Magisk.zip",
            status=StepStatus.SUCCESS,
            message=f"已推送到 {_REMOTE_MAGISK_PATH}",
            output=res.output,
        )

    def _install_magisk(self) -> tuple[StepResult, str]:
        """Step 5: 通过 TWRP 安装 Magisk。

        对应抓包命令 ``shell:twrp install /sdcard/Magisk.zip``。

        TWRP 源码分析（openrecoveryscript.cpp:698）确认：
        - ``twrp install`` 通过 FIFO 发送给 TWRP GUI → ``Insert_ORS_Command``
          → ``run_script_file`` → ``Install_Command`` → ``TWinstall_zip``
        - 整个过程 **同步阻塞**，完成后返回完整日志到 stdout
        - 前置条件已由 ``_wait_for_twrp_gui_ready()`` 确保 GUI 和存储就绪

        安装成功判断：stdout 中包含 Magisk 安装器特征 + ``"- Done"``。

        返回：
            (StepResult, install_log) 元组。
        """
        install_cmd = f"twrp install {_REMOTE_MAGISK_PATH}"
        logger.info("Step 5: 安装 Magisk (adb shell %s)", install_cmd)

        try:
            res = self._adb.shell(install_cmd, timeout=_INSTALL_TIMEOUT)
        except AdbTimeoutError:
            return (
                StepResult(
                    name="安装 Magisk",
                    status=StepStatus.FAILED,
                    message=f"安装命令超时 ({_INSTALL_TIMEOUT}s)",
                ),
                "",
            )
        except AdbError as exc:
            return (
                StepResult(
                    name="安装 Magisk",
                    status=StepStatus.FAILED,
                    message=f"安装命令失败: {exc}",
                ),
                "",
            )

        output = res.output
        logger.info("twrp install 输出 (%d 字符):\n%s", len(output), output)

        if self._is_install_successful(output):
            return (
                StepResult(
                    name="安装 Magisk",
                    status=StepStatus.SUCCESS,
                    message="Magisk 安装成功",
                    output=output,
                ),
                output,
            )

        return (
            StepResult(
                name="安装 Magisk",
                status=StepStatus.FAILED,
                message="安装输出未包含 Magisk 安装器的成功标志",
                output=output,
            ),
            output,
        )

    def _safe_cleanup(self, result: MagiskInstallResult) -> None:
        """Step 6: 清理设备上的 Magisk.zip（安全执行，不抛异常）。

        对应抓包命令 ``shell,v2,TERM=xterm-256color,raw:rm -rf /sdcard/Magisk.zip``。
        无论前面步骤是否成功，都尝试执行清理。
        """
        logger.info(
            "Step 6: 清理 (adb shell rm -rf %s)", _REMOTE_MAGISK_PATH,
        )
        try:
            res = self._adb.shell(f"rm -rf {_REMOTE_MAGISK_PATH}")
            if res.success:
                step = StepResult(
                    name="清理 Magisk.zip",
                    status=StepStatus.SUCCESS,
                    message=f"已删除 {_REMOTE_MAGISK_PATH}",
                )
            else:
                step = StepResult(
                    name="清理 Magisk.zip",
                    status=StepStatus.FAILED,
                    message=f"清理失败 (rc={res.return_code})",
                )
        except AdbError as exc:
            logger.warning("清理失败（不影响整体结果）: %s", exc)
            step = StepResult(
                name="清理 Magisk.zip",
                status=StepStatus.FAILED,
                message=f"清理异常: {exc}",
            )
        result.steps.append(step)

    def _safe_reboot(self, result: MagiskInstallResult) -> None:
        """Step 7: 重启设备（安全执行，不抛异常）。

        对应抓包命令 ``reboot:``。
        无论前面步骤是否成功，都尝试重启，避免设备滞留在 Recovery。

        注意：与 Step 1 相同，``adb reboot`` 会导致 USB 断开，
        返回码非零属于预期行为，始终视为成功。
        """
        logger.info("Step 7: 重启设备 (adb reboot)")
        try:
            self._adb.reboot()
        except AdbError as exc:
            # reboot 导致连接断开时可能抛异常，属于预期行为
            logger.debug("reboot 异常（USB 断开，属预期行为）: %s", exc)

        # reboot 是 fire-and-forget，始终视为成功
        result.steps.append(StepResult(
            name="重启设备",
            status=StepStatus.SUCCESS,
            message="已发送重启命令",
        ))

    # -- 辅助方法 --

    @staticmethod
    def _parse_twrp_version(output: str) -> str:
        """从 ``twrp --version`` 输出中提取版本号。

        抓包响应示例::

            TWRP openrecoveryscript command line tool, TWRP version 3.6.2_11-0

        返回：
            版本号字符串（如 ``"3.6.2_11-0"``），解析失败返回空字符串。
        """
        # 按 "TWRP version " 分割取最后部分
        marker = "TWRP version "
        idx = output.find(marker)
        if idx == -1:
            return ""
        version_part = output[idx + len(marker):].strip()
        # 取第一行、去除尾部空白
        return version_part.splitlines()[0].strip()

    @staticmethod
    def _is_install_successful(log_content: str) -> bool:
        """判断 recovery.log 中是否包含 Magisk 安装器的真实成功输出。

        根据抓包中的安装日志， Magisk 安装器执行时会输出以下特征字符串：:

        - ``"Magisk Installer"`` —— 安装器标题
        - ``"Patching ramdisk"`` —— 核心补丁步骤
        - ``"Flashing new boot image"`` —— 写入新 boot 镜像

        这些标记证明 zip 确实被解压并执行了，而非仅仅被文件名引用。

        同时检查完成标志 ``"- Done"`` 确认安装流程走到了最后。
        """
        # Magisk 安装器特征——证明 zip 被实际执行了
        installer_markers = (
            "Magisk Installer",      # 安装器标题栏
            "Patching ramdisk",      # ramdisk 补丁步骤
            "Flashing new boot image",  # 写入 boot 镜像
        )
        has_installer_output = any(m in log_content for m in installer_markers)

        # 完成标志
        has_done = "- Done" in log_content

        return has_installer_output and has_done


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="install_magisk",
        description="Install Magisk & Root Phone — "
                    "通过 TWRP Recovery 安装 Magisk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-s", "--serial",
        type=str,
        default=None,
        help="设备序列号（多设备时必须指定）",
    )
    parser.add_argument(
        "--adb-path",
        type=str,
        default=None,
        help="adb 可执行文件路径（默认自动查找）",
    )
    parser.add_argument(
        "--magisk-zip",
        type=str,
        default=str(_DEFAULT_LOCAL_MAGISK),
        help=f"Magisk.zip 文件路径（默认: {_DEFAULT_LOCAL_MAGISK.name}）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细日志输出",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> MagiskInstallResult:
    """Install Magisk 主函数。

    既可作为 CLI 入口使用，也可在其他模块中调用。

    参数：
        argv: 命令行参数列表。为 None 时使用 sys.argv。

    返回：
        MagiskInstallResult 对象。
    """
    args = _parse_args(argv)

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        # 创建 ADB 客户端
        adb = AdbClient(
            adb_path=args.adb_path,
            serial=args.serial,
        )

        # 执行安装
        installer = MagiskInstaller(adb, magisk_zip=args.magisk_zip)
        result = installer.install()

        # 输出结果
        print(result)

        if not result.success:
            sys.exit(1)

        return result

    except AdbError as exc:
        logger.error("ADB 错误: %s", exc)
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
