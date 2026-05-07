"""
Install Modules — 通过 Magisk 安装模块。

基于 Wireshark 抓包 ``6.0-Install Modules.txt`` 逐行解析，
严格按照抓包中的命令顺序和返回值判断逻辑实现。

抓包命令完整序列::

    1.  su -c "id"                          — 验证 root 权限
    2.  su -c "magisk --remove-modules -n"  — 移除已有模块（不重启）
    3.  su -c "rm -rf /data/adb/modules/*"  — 清理模块数据目录
    4.  rm -rf /sdcard/modules              — 清理设备端暂存目录
    5.  adb push modules/. /sdcard/modules/ — 推送模块文件
    6.  ls -1 /sdcard/modules/*.zip         — 验证推送结果
    7-10. su -c "magisk --install-module ..." — 按顺序安装每个模块
    11. rm -rf /sdcard/modules              — 清理暂存
    12. reboot                              — 重启设备

命令行用法::

    python install_modules.py
    python install_modules.py --serial SERIAL_NUMBER
    python install_modules.py --modules-dir /path/to/modules

模块用法::

    from install_modules import ModulesInstaller
    from adb_client import AdbClient

    client = AdbClient(serial="SERIAL_NUMBER")
    installer = ModulesInstaller(client)
    result = installer.install()
    print(result)
"""

from __future__ import annotations

import argparse
import enum
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adb_client import AdbClient, AdbError, AdbTimeoutError
from load_device import select_device

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 设备端模块暂存目录（与抓包一致）
_REMOTE_MODULES_DIR: str = "/sdcard/modules"

#: Magisk 模块数据目录
_DATA_MODULES_DIR: str = "/data/adb/modules"

#: 默认本地 modules 目录（项目根目录）
_DEFAULT_LOCAL_MODULES_DIR: Path = Path(__file__).resolve().parent / "modules"

#: 单个模块安装超时（秒）
_MODULE_INSTALL_TIMEOUT: int = 120

#: 推送目录超时（秒）
_PUSH_TIMEOUT: int = 300


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
class ModuleInstallResult:
    """单个模块的安装结果。

    Attributes:
        name: 模块文件名。
        success: 是否安装成功。
        output: 安装过程的完整输出。
    """

    name: str
    success: bool = False
    output: str = ""


@dataclass
class ModulesInstallResult:
    """模块安装流程整体结果。

    Attributes:
        success: 安装是否全部成功。
        modules: 各模块安装结果。
        steps: 各步骤执行结果列表。
        error: 失败时的错误信息。
    """

    success: bool = False
    modules: list[ModuleInstallResult] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "success": self.success,
            "modules": [
                {"name": m.name, "success": m.success}
                for m in self.modules
            ],
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
            f"  {status_icon}  Modules Installation Result",
            "=" * 60,
            f"  Modules:  {len(self.modules)}",
            f"  Overall:  {'SUCCESS' if self.success else 'FAILED'}",
        ]
        if self.error:
            lines.append(f"  Error:    {self.error}")
        lines.append("-" * 60)
        for step in self.steps:
            icon = {"success": "+", "failed": "X", "skipped": "o"}[step.status.value]
            lines.append(f"  [{icon}] {step.name}: {step.message}")
        if self.modules:
            lines.append("-" * 60)
            for mod in self.modules:
                icon = "+" if mod.success else "X"
                lines.append(f"  [{icon}] {mod.name}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 安装器
# ---------------------------------------------------------------------------

class ModulesInstaller:
    """按 Wireshark 抓包流程安装 Magisk 模块。

    严格按照 ``6.0-Install Modules.txt`` 中记录的
    命令顺序和返回值判断逻辑执行。

    参数：
        adb: AdbClient 实例。
        modules_dir: 本地 modules 目录路径。
    """

    def __init__(
        self,
        adb: AdbClient,
        modules_dir: str | Path = _DEFAULT_LOCAL_MODULES_DIR,
    ) -> None:
        self._adb = adb
        self._modules_dir = Path(modules_dir)

    def install(self) -> ModulesInstallResult:
        """执行完整的模块安装流程。

        按抓包顺序依次执行：

        1.  ``su -c "id"``                          — 验证 root 权限
        2.  ``su -c "magisk --remove-modules -n"``  — 移除已有模块
        3.  ``su -c "rm -rf /data/adb/modules/*"``  — 清理模块数据
        4.  ``rm -rf /sdcard/modules``              — 清理暂存
        5.  ``adb push modules/. /sdcard/modules/`` — 推送模块
        6.  ``ls -1 /sdcard/modules/*.zip``         — 验证推送
        7-N. ``su -c "magisk --install-module ..."`` — 逐个安装
        N+1. ``rm -rf /sdcard/modules``             — 清理
        N+2. ``reboot``                             — 重启

        返回：
            ModulesInstallResult 对象。
        """
        result = ModulesInstallResult()

        # -- 前置检查：本地 modules 目录 --
        zip_files = self._find_local_modules()
        if not zip_files:
            result.error = f"本地 modules 目录中无 .zip 文件: {self._modules_dir}"
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
            message=f"找到 {len(zip_files)} 个模块: "
                    + ", ".join(f.name for f in zip_files),
        ))

        # -- Step 1: 验证 root 权限（对应抓包 shell:su -c "id"）--
        step = self._verify_root()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # -- Step 2: 移除已有模块（对应抓包 su -c "magisk --remove-modules -n"）--
        step = self._remove_existing_modules()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # -- Step 3: 清理模块数据目录（对应抓包 su -c "rm -rf /data/adb/modules/*"）--
        step = self._clean_data_modules()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # -- Step 4: 清理设备端暂存目录（对应抓包 rm -rf /sdcard/modules）--
        step = self._clean_remote_staging()
        result.steps.append(step)
        # 清理失败不中断（目录可能本就不存在）

        # -- Step 5: 推送模块目录（对应抓包 sync 协议批量传输）--
        step = self._push_modules()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            self._safe_cleanup(result)
            self._safe_reboot(result)
            return result

        # -- Step 6: 验证推送结果（对应抓包 shell:ls -1 /sdcard/modules/*.zip）--
        step, remote_zips = self._verify_push(zip_files)
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            self._safe_cleanup(result)
            self._safe_reboot(result)
            return result

        # -- Step 7-N: 按顺序安装每个模块 --
        all_success = True
        for remote_zip in remote_zips:
            mod_result = self._install_single_module(remote_zip)
            result.modules.append(mod_result)
            step_status = StepStatus.SUCCESS if mod_result.success else StepStatus.FAILED
            result.steps.append(StepResult(
                name=f"安装 {Path(remote_zip).name}",
                status=step_status,
                message="安装成功" if mod_result.success else "安装失败",
                output=mod_result.output,
            ))
            if not mod_result.success:
                all_success = False
                # 某个模块安装失败不中断，继续安装其他模块

        # -- Step N+1: 清理暂存（对应抓包 rm -rf /sdcard/modules）--
        self._safe_cleanup(result)

        # -- Step N+2: 重启设备（对应抓包 reboot:）--
        self._safe_reboot(result)

        result.success = all_success
        if not all_success:
            failed = [m.name for m in result.modules if not m.success]
            result.error = f"以下模块安装失败: {', '.join(failed)}"

        return result

    # -- 私有方法：各步骤实现 --

    def _find_local_modules(self) -> list[Path]:
        """查找本地 modules 目录中的 .zip 文件，按文件名排序。

        文件名前缀（如 ``1.``, ``2.``）决定安装顺序。
        """
        if not self._modules_dir.is_dir():
            return []
        zips = sorted(self._modules_dir.glob("*.zip"))
        return zips

    def _verify_root(self) -> StepResult:
        """Step 1: 验证 root 权限。

        对应抓包命令 ``shell:su -c "id"``。
        预期输出包含 ``uid=0(root)``。
        """
        logger.info("Step 1: 验证 root 权限 (su -c \"id\")")
        try:
            res = self._adb.shell('su -c "id"')
        except AdbError as exc:
            return StepResult(
                name="验证 root",
                status=StepStatus.FAILED,
                message=f"执行 id 命令失败: {exc}",
            )

        output = res.output
        if "uid=0(root)" in output:
            logger.info("root 权限验证通过: %s", output.strip())
            return StepResult(
                name="验证 root",
                status=StepStatus.SUCCESS,
                message="root 权限已确认",
                output=output,
            )

        return StepResult(
            name="验证 root",
            status=StepStatus.FAILED,
            message=f"设备未获取 root 权限，输出: {output!r}",
            output=output,
        )

    def _remove_existing_modules(self) -> StepResult:
        """Step 2: 移除已有 Magisk 模块（不重启）。

        对应抓包命令 ``shell:su -c "magisk --remove-modules -n"``。
        ``-n`` 参数表示仅标记移除，不触发重启。
        """
        logger.info('Step 2: 移除已有模块 (su -c "magisk --remove-modules -n")')
        try:
            res = self._adb.shell('su -c "magisk --remove-modules -n"')
        except AdbError as exc:
            return StepResult(
                name="移除已有模块",
                status=StepStatus.FAILED,
                message=f"移除模块失败: {exc}",
            )

        # 命令执行即视为成功（即使没有模块可移除）
        logger.info("移除模块完成: %s", res.output.strip())
        return StepResult(
            name="移除已有模块",
            status=StepStatus.SUCCESS,
            message="已移除已有模块",
            output=res.output,
        )

    def _clean_data_modules(self) -> StepResult:
        """Step 3: 清理 Magisk 模块数据目录。

        对应抓包命令 ``shell:su -c "rm -rf /data/adb/modules/*"``。
        """
        logger.info(
            'Step 3: 清理模块数据 (su -c "rm -rf %s/*")', _DATA_MODULES_DIR,
        )
        try:
            res = self._adb.shell(f'su -c "rm -rf {_DATA_MODULES_DIR}/*"')
        except AdbError as exc:
            return StepResult(
                name="清理模块数据",
                status=StepStatus.FAILED,
                message=f"清理失败: {exc}",
            )

        logger.info("模块数据目录已清理")
        return StepResult(
            name="清理模块数据",
            status=StepStatus.SUCCESS,
            message=f"已清理 {_DATA_MODULES_DIR}/*",
            output=res.output,
        )

    def _clean_remote_staging(self) -> StepResult:
        """Step 4 / Step N+1: 清理设备端暂存目录。

        对应抓包命令 ``shell,v2:rm -rf /sdcard/modules``。
        """
        logger.info(
            "Step 4: 清理暂存目录 (rm -rf %s)", _REMOTE_MODULES_DIR,
        )
        try:
            res = self._adb.shell(f"rm -rf {_REMOTE_MODULES_DIR}")
        except AdbError as exc:
            return StepResult(
                name="清理暂存目录",
                status=StepStatus.FAILED,
                message=f"清理失败: {exc}",
            )

        return StepResult(
            name="清理暂存目录",
            status=StepStatus.SUCCESS,
            message=f"已清理 {_REMOTE_MODULES_DIR}",
        )

    def _push_modules(self) -> StepResult:
        """Step 5: 推送本地 modules 目录到设备。

        对应抓包中的 sync 协议批量传输序列：
        ``sync:`` → ``STA2 /sdcard/modules`` → ``SND2`` → ``DATA`` → ``OKAY``

        使用 ``adb push modules/. /sdcard/modules/`` 推送整个目录。
        """
        logger.info(
            "Step 5: 推送模块目录 (adb push %s/. %s/)",
            self._modules_dir, _REMOTE_MODULES_DIR,
        )
        try:
            res = self._adb.push_dir(
                self._modules_dir, _REMOTE_MODULES_DIR + "/",
                timeout=_PUSH_TIMEOUT,
            )
        except FileNotFoundError as exc:
            return StepResult(
                name="推送模块",
                status=StepStatus.FAILED,
                message=str(exc),
            )
        except AdbError as exc:
            return StepResult(
                name="推送模块",
                status=StepStatus.FAILED,
                message=f"推送异常: {exc}",
            )

        if not res.success:
            return StepResult(
                name="推送模块",
                status=StepStatus.FAILED,
                message=f"推送失败 (rc={res.return_code}): {res.stderr.strip()}",
            )

        logger.info("推送完成: %s", res.output.strip())
        return StepResult(
            name="推送模块",
            status=StepStatus.SUCCESS,
            message=f"已推送到 {_REMOTE_MODULES_DIR}/",
            output=res.output,
        )

    def _verify_push(
        self, local_zips: list[Path],
    ) -> tuple[StepResult, list[str]]:
        """Step 6: 验证推送结果。

        对应抓包命令 ``shell:ls -1 /sdcard/modules/*.zip``。

        返回：
            (StepResult, remote_zip_paths) 元组。
            remote_zip_paths 按文件名排序，与抓包中的安装顺序一致。
        """
        logger.info(
            "Step 6: 验证推送 (ls -1 %s/*.zip)", _REMOTE_MODULES_DIR,
        )
        try:
            res = self._adb.shell(f"ls -1 {_REMOTE_MODULES_DIR}/*.zip")
        except AdbError as exc:
            return (
                StepResult(
                    name="验证推送",
                    status=StepStatus.FAILED,
                    message=f"列出文件失败: {exc}",
                ),
                [],
            )

        if not res.success or "No such file" in res.output:
            return (
                StepResult(
                    name="验证推送",
                    status=StepStatus.FAILED,
                    message="设备端未找到模块文件",
                    output=res.output,
                ),
                [],
            )

        # 解析远端文件列表
        remote_zips = sorted(
            line.strip()
            for line in res.output.splitlines()
            if line.strip() and line.strip().endswith(".zip")
        )

        # 校验数量一致
        if len(remote_zips) != len(local_zips):
            return (
                StepResult(
                    name="验证推送",
                    status=StepStatus.FAILED,
                    message=f"文件数量不匹配: 本地 {len(local_zips)}, "
                            f"远端 {len(remote_zips)}",
                    output=res.output,
                ),
                [],
            )

        logger.info("推送验证通过: %d 个模块", len(remote_zips))
        return (
            StepResult(
                name="验证推送",
                status=StepStatus.SUCCESS,
                message=f"已验证 {len(remote_zips)} 个模块文件",
                output=res.output,
            ),
            remote_zips,
        )

    def _install_single_module(self, remote_zip: str) -> ModuleInstallResult:
        """安装单个模块。

        对应抓包命令 ``shell:su -c "magisk --install-module <path>"``。

        Magisk CLI ``--install-module`` 是同步阻塞命令，
        完成后返回完整安装日志到 stdout。
        安装成功判断：stdout 中包含 ``"- Done"`` 标志。

        参数：
            remote_zip: 设备端模块 zip 文件路径。

        返回：
            ModuleInstallResult 对象。
        """
        module_name = Path(remote_zip).name
        install_cmd = f'su -c "magisk --install-module {remote_zip}"'
        logger.info("安装模块: %s", module_name)

        try:
            res = self._adb.shell(install_cmd, timeout=_MODULE_INSTALL_TIMEOUT)
        except AdbTimeoutError:
            logger.error("模块安装超时: %s", module_name)
            return ModuleInstallResult(
                name=module_name,
                success=False,
                output=f"安装超时 ({_MODULE_INSTALL_TIMEOUT}s)",
            )
        except AdbError as exc:
            logger.error("模块安装异常: %s — %s", module_name, exc)
            return ModuleInstallResult(
                name=module_name,
                success=False,
                output=str(exc),
            )

        output = res.output
        logger.info(
            "模块 %s 安装输出 (%d 字符):\n%s",
            module_name, len(output), output,
        )

        success = "- Done" in output
        if success:
            logger.info("模块 %s 安装成功", module_name)
        else:
            logger.error("模块 %s 安装失败（输出中未包含 '- Done'）", module_name)

        return ModuleInstallResult(
            name=module_name,
            success=success,
            output=output,
        )

    def _safe_cleanup(self, result: ModulesInstallResult) -> None:
        """清理设备端暂存目录（安全执行，不抛异常）。

        对应抓包命令 ``shell,v2:rm -rf /sdcard/modules``。
        无论前面步骤是否成功，都尝试执行清理。
        """
        logger.info("清理暂存: rm -rf %s", _REMOTE_MODULES_DIR)
        try:
            res = self._adb.shell(f"rm -rf {_REMOTE_MODULES_DIR}")
            if res.success:
                step = StepResult(
                    name="清理暂存",
                    status=StepStatus.SUCCESS,
                    message=f"已删除 {_REMOTE_MODULES_DIR}",
                )
            else:
                step = StepResult(
                    name="清理暂存",
                    status=StepStatus.FAILED,
                    message=f"清理失败 (rc={res.return_code})",
                )
        except AdbError as exc:
            logger.warning("清理失败（不影响整体结果）: %s", exc)
            step = StepResult(
                name="清理暂存",
                status=StepStatus.FAILED,
                message=f"清理异常: {exc}",
            )
        result.steps.append(step)

    def _safe_reboot(self, result: ModulesInstallResult) -> None:
        """重启设备（安全执行，不抛异常）。

        对应抓包命令 ``reboot:``。
        无论前面步骤是否成功，都尝试重启。

        注意：``adb reboot`` 会导致 USB 断开，
        返回码非零属于预期行为，始终视为成功。
        """
        logger.info("重启设备 (adb reboot)")
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


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="install_modules",
        description="Install Modules — 通过 Magisk 安装模块",
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
        "--modules-dir",
        type=str,
        default=str(_DEFAULT_LOCAL_MODULES_DIR),
        help=f"modules 目录路径（默认: {_DEFAULT_LOCAL_MODULES_DIR.name}/）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细日志输出",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> ModulesInstallResult:
    """Install Modules 主函数。

    既可作为 CLI 入口使用，也可在其他模块中调用。

    参数：
        argv: 命令行参数列表。为 None 时使用 sys.argv。

    返回：
        ModulesInstallResult 对象。
    """
    args = _parse_args(argv)

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        # 通过 load_device 选择设备
        adb = select_device(
            adb_path=args.adb_path,
            serial=args.serial,
        )

        # 执行安装
        installer = ModulesInstaller(adb, modules_dir=args.modules_dir)
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
