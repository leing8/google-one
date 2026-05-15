"""
Install Modules CLI 入口。

支持 python -m michanger.install_modules 运行。
批量安装 Magisk 模块。

用法：
    python -m michanger.install_modules [--adb-path PATH] [--serial SERIAL]
                                        [--modules-dir DIR] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .install_modules import install_modules
from .models import InstallModulesResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/install_modules/__main__.py → 3 级 parent 到项目根
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
        prog="michanger.install_modules",
        description=(
            "Install Modules — "
            "批量安装 Magisk 模块（Zygisk、Shamiko、TrickyStore 等）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.install_modules\n"
            "  python -m michanger.install_modules --serial ABCD1234\n"
            "  python -m michanger.install_modules --modules-dir /path/to/modules\n"
            "  python -m michanger.install_modules --dry-run\n"
            "  python -m michanger.install_modules -v\n"
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


def _print_result(result: InstallModulesResult) -> None:
    """打印安装结果。

    Args:
        result: 模块安装结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  模块安装结果: {status}")
    print("=" * 60)
    print(f"  Root 验证:    {'通过' if result.root_verified else '失败'}")
    print(f"  旧模块移除:  {'成功' if result.modules_removed else '跳过/失败'}")
    print(f"  文件推送:    {'成功' if result.modules_pushed else '失败'}")
    print(f"  安装成功:    {result.success_count}/{result.total_count}")
    print(f"  临时文件清理: {'完成' if result.cleanup_done else '失败'}")
    print(f"  设备重启:    {'已重启' if result.reboot_initiated else '未重启'}")
    print()

    # 逐个模块的安装状态
    if result.install_results:
        print("  模块详情:")
        for r in result.install_results:
            icon = "✓" if r.success else "✗"
            print(f"    {icon} {r.module_name}")
        print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 验证模块目录存在
    modules_dir: Path = args.modules_dir
    if not modules_dir.is_dir():
        print(
            f"错误：模块目录不存在：{modules_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 验证目录中有 .zip 文件
    zip_count = sum(
        1 for f in modules_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".zip"
    )
    if zip_count == 0:
        print(
            f"错误：模块目录中未找到 .zip 文件：{modules_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(args.adb_path)

    try:
        result = install_modules(
            adb_path=args.adb_path,
            serial=serial,
            modules_dir=modules_dir,
            dry_run=args.dry_run,
        )
    except AdbError as exc:
        log.error("Install Modules 失败: %s", exc)
        sys.exit(1)
    except FileNotFoundError as exc:
        log.error("文件未找到: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
