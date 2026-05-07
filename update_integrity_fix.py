"""
Update Integrity Fix — 更新 Play Integrity Fix 模块。

基于 Wireshark 抓包 ``8.0-Update Integrity Fix.txt`` 逐行解析，
严格按照抓包中的命令顺序和返回值判断逻辑实现。

抓包命令完整序列::

    1.  su -c "id"                                — 验证 root 权限
    2.  rm -rf /sdcard/modules/*.zip              — 清理旧 zip
    3.  adb push (sync 协议) → /sdcard/modules/   — 推送模块文件
    4.  su -c "magisk --install-module ..."        — 安装每个模块
    5.  rm -rf /sdcard/modules/                   — 清理暂存
    6.  su -c mount -o rw,remount /               — 挂载根分区读写
    7.  su -c mount -o rw,remount /product        — 挂载 product 读写
    8.  su -c mount -o rw,remount /vendor         — 挂载 vendor 读写
    9.  配置 Tricky Store config hash             — 写入指纹 hash
    10. 配置 security_patch.txt                   — 写入安全补丁日期
    11. reboot                                    — 重启设备

命令行用法::

    python update_integrity_fix.py
    python update_integrity_fix.py --serial SERIAL_NUMBER
    python update_integrity_fix.py --modules-dir "1-Update Integrity Fix"

模块用法::

    from update_integrity_fix import IntegrityFixUpdater
    from adb_client import AdbClient

    client = AdbClient(serial="SERIAL_NUMBER")
    updater = IntegrityFixUpdater(client)
    result = updater.update()
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
# 常量 — 严格对应抓包中的路径和值
# ---------------------------------------------------------------------------

#: 设备端模块暂存目录
_REMOTE_MODULES_DIR: str = "/sdcard/modules"

#: 默认本地模块目录
_DEFAULT_LOCAL_DIR: Path = Path(__file__).resolve().parent / "1-Update Integrity Fix"

#: Tricky Store 指纹 hash（对应抓包中 printf 写入的值）
_CONFIG_HASH: str = (
    "cd0315e9f43897fcd9eef362b4a43b77"
    "d801d99b6f18fe3845028e92b6a1b836"
)

#: 安全补丁日期（对应抓包中 printf 写入的值）
_SECURITY_PATCH: str = "all=2026-04-05"

#: 系统配置文件路径
_SYSTEM_CONFIG_PATH: str = "/system/etc/config"

#: Tricky Store 安全补丁路径
_TRICKY_STORE_PATCH_PATH: str = "/data/adb/tricky_store/security_patch.txt"

#: 需要 rw 挂载的分区列表（对应抓包顺序）
_PARTITIONS_TO_REMOUNT: tuple[str, ...] = ("/", "/product", "/vendor")

#: 模块安装超时（秒）
_MODULE_INSTALL_TIMEOUT: int = 120

#: 推送超时（秒）
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
    """单步骤执行结果。"""
    name: str
    status: StepStatus
    message: str
    output: str = ""


@dataclass
class IntegrityFixResult:
    """Update Integrity Fix 流程整体结果。"""
    success: bool = False
    steps: list[StepResult] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "steps": [
                {"name": s.name, "status": s.status.value, "message": s.message}
                for s in self.steps
            ],
            "error": self.error,
        }

    def __str__(self) -> str:
        icon = "[OK]" if self.success else "[FAIL]"
        lines = [
            "=" * 60,
            f"  {icon}  Update Integrity Fix Result",
            "=" * 60,
            f"  Overall: {'SUCCESS' if self.success else 'FAILED'}",
        ]
        if self.error:
            lines.append(f"  Error:   {self.error}")
        lines.append("-" * 60)
        for step in self.steps:
            sym = {"success": "+", "failed": "X", "skipped": "o"}[step.status.value]
            lines.append(f"  [{sym}] {step.name}: {step.message}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 核心执行器
# ---------------------------------------------------------------------------

class IntegrityFixUpdater:
    """按 Wireshark 抓包流程更新 Play Integrity Fix。

    严格按照 ``8.0-Update Integrity Fix.txt`` 中记录的
    命令顺序和返回值判断逻辑执行。

    参数：
        adb: AdbClient 实例。
        modules_dir: 本地模块 zip 文件所在目录。
    """

    def __init__(
        self,
        adb: AdbClient,
        modules_dir: str | Path = _DEFAULT_LOCAL_DIR,
    ) -> None:
        self._adb = adb
        self._modules_dir = Path(modules_dir)

    def update(self) -> IntegrityFixResult:
        """执行完整的 Update Integrity Fix 流程。"""
        result = IntegrityFixResult()

        # 前置：检查本地 zip 文件
        zip_files = self._find_local_zips()
        if not zip_files:
            result.error = f"本地目录无 .zip 文件: {self._modules_dir}"
            result.steps.append(StepResult(
                "检查本地文件", StepStatus.FAILED, result.error,
            ))
            return result
        result.steps.append(StepResult(
            "检查本地文件", StepStatus.SUCCESS,
            f"找到 {len(zip_files)} 个模块: "
            + ", ".join(f.name for f in zip_files),
        ))

        # Step 1: su -c "id"
        step = self._verify_root()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # Step 2: rm -rf /sdcard/modules/*.zip
        step = self._clean_old_modules()
        result.steps.append(step)

        # Step 3: adb push → /sdcard/modules/
        step = self._push_modules()
        result.steps.append(step)
        if step.status == StepStatus.FAILED:
            result.error = step.message
            return result

        # Step 4: magisk --install-module (每个 zip)
        all_installed = True
        for zip_file in zip_files:
            remote_path = f"{_REMOTE_MODULES_DIR}/{zip_file.name}"
            step = self._install_module(remote_path)
            result.steps.append(step)
            if step.status == StepStatus.FAILED:
                all_installed = False

        # Step 5: rm -rf /sdcard/modules/
        step = self._cleanup_staging()
        result.steps.append(step)

        # Step 6-8: mount -o rw,remount (/, /product, /vendor)
        self._remount_all(result)

        # Step 9: 配置 Tricky Store config hash
        self._configure_config_hash(result)

        # Step 10: 再次挂载 + 配置 security_patch
        self._remount_all(result)
        self._configure_security_patch(result)

        # Step 11: reboot
        self._reboot(result)

        result.success = all_installed
        if not all_installed:
            result.error = "部分模块安装失败"

        return result

    # -- 私有方法 --

    def _find_local_zips(self) -> list[Path]:
        """查找本地目录中的 .zip 文件，按文件名排序。"""
        if not self._modules_dir.is_dir():
            return []
        return sorted(self._modules_dir.glob("*.zip"))

    def _verify_root(self) -> StepResult:
        """对应抓包: shell:su -c "id"。"""
        logger.info('Step 1: 验证 root (su -c "id")')
        try:
            res = self._adb.shell('su -c "id"')
        except AdbError as exc:
            return StepResult("验证 root", StepStatus.FAILED, str(exc))

        if "uid=0(root)" in res.output:
            return StepResult(
                "验证 root", StepStatus.SUCCESS,
                "root 权限已确认", res.output,
            )
        return StepResult(
            "验证 root", StepStatus.FAILED,
            f"未获取 root: {res.output!r}", res.output,
        )

    def _clean_old_modules(self) -> StepResult:
        """对应抓包: shell:rm -rf /sdcard/modules/*.zip。"""
        logger.info("Step 2: 清理旧 zip")
        try:
            self._adb.shell(f"rm -rf {_REMOTE_MODULES_DIR}/*.zip")
        except AdbError as exc:
            return StepResult("清理旧 zip", StepStatus.FAILED, str(exc))
        return StepResult(
            "清理旧 zip", StepStatus.SUCCESS,
            f"已清理 {_REMOTE_MODULES_DIR}/*.zip",
        )

    def _push_modules(self) -> StepResult:
        """对应抓包: sync 协议推送文件到 /sdcard/modules/。"""
        logger.info("Step 3: 推送模块文件")
        try:
            res = self._adb.push_dir(
                self._modules_dir,
                _REMOTE_MODULES_DIR + "/",
                timeout=_PUSH_TIMEOUT,
            )
        except FileNotFoundError as exc:
            return StepResult("推送模块", StepStatus.FAILED, str(exc))
        except AdbError as exc:
            return StepResult("推送模块", StepStatus.FAILED, str(exc))

        if not res.success:
            return StepResult(
                "推送模块", StepStatus.FAILED,
                f"推送失败 (rc={res.return_code})",
            )
        return StepResult(
            "推送模块", StepStatus.SUCCESS,
            f"已推送到 {_REMOTE_MODULES_DIR}/", res.output,
        )

    def _install_module(self, remote_zip: str) -> StepResult:
        """对应抓包: shell:su -c "magisk --install-module <path>"。"""
        name = Path(remote_zip).name
        cmd = f'su -c "magisk --install-module {remote_zip}"'
        logger.info("安装模块: %s", name)

        try:
            res = self._adb.shell(cmd, timeout=_MODULE_INSTALL_TIMEOUT)
        except AdbTimeoutError:
            return StepResult(f"安装 {name}", StepStatus.FAILED, "超时")
        except AdbError as exc:
            return StepResult(f"安装 {name}", StepStatus.FAILED, str(exc))

        if "- Done" in res.output:
            return StepResult(
                f"安装 {name}", StepStatus.SUCCESS,
                "安装成功", res.output,
            )
        return StepResult(
            f"安装 {name}", StepStatus.FAILED,
            "输出中未包含 '- Done'", res.output,
        )

    def _cleanup_staging(self) -> StepResult:
        """对应抓包: shell:rm -rf /sdcard/modules/。"""
        logger.info("清理暂存目录")
        try:
            self._adb.shell(f"rm -rf {_REMOTE_MODULES_DIR}/")
        except AdbError as exc:
            return StepResult("清理暂存", StepStatus.FAILED, str(exc))
        return StepResult("清理暂存", StepStatus.SUCCESS, "已清理")

    def _remount_partition(self, partition: str) -> StepResult:
        """对应抓包: shell,v2:su -c mount -o rw,remount <partition>。"""
        cmd = f'su -c "mount -o rw,remount {partition}"'
        logger.info("挂载分区 rw: %s", partition)
        try:
            self._adb.shell(cmd)
        except AdbError as exc:
            return StepResult(
                f"挂载 {partition}", StepStatus.FAILED, str(exc),
            )
        return StepResult(
            f"挂载 {partition}", StepStatus.SUCCESS,
            f"已挂载 {partition} 为 rw",
        )

    def _remount_all(self, result: IntegrityFixResult) -> None:
        """挂载所有分区为 rw（对应抓包中的三次 mount 命令）。"""
        for partition in _PARTITIONS_TO_REMOUNT:
            step = self._remount_partition(partition)
            result.steps.append(step)

    def _shell_write_file(
        self,
        content: str,
        staging_path: str,
        target_path: str,
        step_name: str,
        result: IntegrityFixResult,
    ) -> bool:
        """通过 sdcard 中转写入系统文件（抓包中的标准模式）。

        对应抓包序列:
        1. rm -rf <staging_path>
        2. rm -rf <target_path>
        3. printf '<content>' > <staging_path>
        4. mv <staging_path> <target_path>
        5. chmod 644 <target_path>
        """
        commands = [
            (f'su -c "rm -rf {staging_path}"', f"清理 {staging_path}"),
            (f'su -c "rm -rf {target_path}"', f"清理 {target_path}"),
            (
                f"su -c \"printf '{content}' > {staging_path}\"",
                f"写入 {staging_path}",
            ),
            (
                f'su -c "mv {staging_path} {target_path}"',
                f"移动到 {target_path}",
            ),
            (f'su -c "chmod 644 {target_path}"', f"设置权限 644"),
        ]

        for cmd, desc in commands:
            logger.info("%s: %s", step_name, desc)
            try:
                res = self._adb.shell(cmd)
                if not res.success:
                    result.steps.append(StepResult(
                        f"{step_name} - {desc}", StepStatus.FAILED,
                        f"rc={res.return_code}: {res.stderr.strip()}",
                    ))
                    return False
            except AdbError as exc:
                result.steps.append(StepResult(
                    f"{step_name} - {desc}", StepStatus.FAILED, str(exc),
                ))
                return False

        result.steps.append(StepResult(
            step_name, StepStatus.SUCCESS,
            f"已写入 {target_path}",
        ))
        return True

    def _configure_config_hash(self, result: IntegrityFixResult) -> None:
        """对应抓包: 写入 Tricky Store config hash 到 /system/etc/config。"""
        self._shell_write_file(
            content=_CONFIG_HASH,
            staging_path="/sdcard/config",
            target_path=_SYSTEM_CONFIG_PATH,
            step_name="配置 config hash",
            result=result,
        )

    def _configure_security_patch(self, result: IntegrityFixResult) -> None:
        """对应抓包: 写入安全补丁到 tricky_store/security_patch.txt。"""
        self._shell_write_file(
            content=_SECURITY_PATCH,
            staging_path="/sdcard/security_patch.txt",
            target_path=_TRICKY_STORE_PATCH_PATH,
            step_name="配置 security_patch",
            result=result,
        )

    def _reboot(self, result: IntegrityFixResult) -> None:
        """对应抓包: reboot:。"""
        logger.info("重启设备")
        try:
            self._adb.reboot()
        except AdbError:
            # reboot 导致 USB 断开，属预期行为
            pass
        result.steps.append(StepResult(
            "重启设备", StepStatus.SUCCESS, "已发送重启命令",
        ))


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update_integrity_fix",
        description="Update Integrity Fix — 更新 PIF 模块",
    )
    parser.add_argument(
        "-s", "--serial", type=str, default=None,
        help="设备序列号",
    )
    parser.add_argument(
        "--adb-path", type=str, default=None,
        help="adb 可执行文件路径",
    )
    parser.add_argument(
        "--modules-dir", type=str,
        default=str(_DEFAULT_LOCAL_DIR),
        help=f"模块目录 (默认: {_DEFAULT_LOCAL_DIR.name}/)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="详细日志",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> IntegrityFixResult:
    """Update Integrity Fix 主函数。"""
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        adb = select_device(adb_path=args.adb_path, serial=args.serial)
        updater = IntegrityFixUpdater(adb, modules_dir=args.modules_dir)
        result = updater.update()
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
