"""
Update Integrity Fix CLI 入口。

支持 python -m michanger.update_integrity_fix 运行。

用法：
    python -m michanger.update_integrity_fix [--adb-path PATH] [--serial SERIAL]
                                              [--modules-dir DIR] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .models import UpdateIntegrityFixResult
from .update_integrity_fix import update_integrity_fix

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
)

# 默认模块目录：模块包内的 modules/ 子目录
_DEFAULT_MODULES_DIR: Path = (
    Path(__file__).resolve().parent / "modules"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践：
    - 使用 prog 指定程序名
    - 使用 type=Path 自动转换路径参数
    - 提供 epilog 示例用法

    参考：https://docs.python.org/3/library/argparse.html
    """
    parser = argparse.ArgumentParser(
        prog="michanger.update_integrity_fix",
        description=(
            "Update Integrity Fix — "
            "更新 Tricky Store + PIF Premium 并写入系统配置"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.update_integrity_fix\n"
            "  python -m michanger.update_integrity_fix --serial ABCD1234\n"
            "  python -m michanger.update_integrity_fix --dry-run\n"
            "  python -m michanger.update_integrity_fix -v\n"
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=_DEFAULT_ADB_PATH,
        help=f"adb 可执行文件路径（默认：{_DEFAULT_ADB_PATH}）",
    )
    parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help="设备序列号（默认：自动检测第一台在线设备）",
    )
    parser.add_argument(
        "--modules-dir",
        type=Path,
        default=_DEFAULT_MODULES_DIR,
        help=f"模块文件目录（默认：{_DEFAULT_MODULES_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印命令序列，不实际执行",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _print_result(result: UpdateIntegrityFixResult) -> None:
    """打印执行结果。"""
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  Update Integrity Fix 结果: {status}")
    print("=" * 60)
    print(f"  Root 验证:         {'通过' if result.root_verified else '失败'}")
    print(f"  旧模块清理:       {'完成' if result.modules_cleaned else '跳过'}")

    if result.tricky_store_result is not None:
        ts = result.tricky_store_result
        print(f"  Tricky Store OSS:  {'成功' if ts.success else '失败'}")
    else:
        print("  Tricky Store OSS:  未执行")

    if result.pif_premium_result is not None:
        pif = result.pif_premium_result
        print(f"  PIF Premium:       {'成功' if pif.success else '失败'}")
    else:
        print("  PIF Premium:       未执行")

    if result.system_config is not None:
        sc = result.system_config
        print(f"  Config 哈希写入:   {'成功' if sc.config_written else '失败'}")
        print(f"  Security Patch:    {'成功' if sc.security_patch_written else '失败'}")
        print(f"    → {sc.security_patch_value}")
    else:
        print("  系统配置:          未执行")

    print(f"  设备重启:          {'已重启' if result.reboot_initiated else '未重启'}")
    print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 模块目录可以不存在（会自动下载）
    modules_dir: Path = args.modules_dir

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(args.adb_path)

    try:
        result = update_integrity_fix(
            adb_path=args.adb_path,
            serial=serial,
            modules_dir=modules_dir,
            dry_run=args.dry_run,
        )
    except AdbError as exc:
        log.error("Update Integrity Fix 失败: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        log.error("文件未找到: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
