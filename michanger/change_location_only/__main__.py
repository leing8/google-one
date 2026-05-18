"""
Change Location Only CLI 入口。

支持 python -m michanger.change_location_only 运行。
清除位置历史、在 TWRP Recovery 中替换 mi_info.json 实现位置信息变更。

用法：
    python -m michanger.change_location_only
    python -m michanger.change_location_only -s SERIAL_NUMBER -v
    python -m michanger.change_location_only --profile blazer

参考：
- https://docs.python.org/3/library/argparse.html
- https://docs.python.org/3/howto/logging.html
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from michanger.common import AdbError, auto_detect_serial, setup_logging
from .change_location_only import change_location_only
from .models import ChangeLocationResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/change_location_only/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "platform-tools"
    / "adb.exe"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践。

    参考：https://docs.python.org/3/library/argparse.html

    Returns:
        配置完成的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="michanger.change_location_only",
        description=(
            "Change Location Only — "
            "位置信息变更（替换 mi_info.json + 清理位置历史）"
            "（严格还原 15.0-Change Location Only.pcapng）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.change_location_only\n"
            "  python -m michanger.change_location_only"
            " -s SERIAL_NUMBER\n"
            "  python -m michanger.change_location_only"
            " --profile blazer\n"
            "  python -m michanger.change_location_only -v\n"
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=_DEFAULT_ADB_PATH,
        help=f"adb 可执行文件路径（默认：{_DEFAULT_ADB_PATH}）",
    )
    parser.add_argument(
        "-s",
        "--serial",
        type=str,
        default=None,
        help="设备序列号（默认：自动检测第一台在线设备）",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="设备配置名称（不含 .json 后缀，默认：第一个可用配置）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _print_result(result: ChangeLocationResult) -> None:
    """打印执行结果。

    Args:
        result: 位置信息变更结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  Change Location Only 结果: {status}")
    print("=" * 60)
    print(f"  设备序列号:    {result.serial}")
    print(f"  mi 目录路径:   {result.mi_dir_path}")
    print(f"  pm clear 输出: {result.pm_clear_output}")
    print(
        f"  阶段结果:      "
        f"{result.success_count}/{result.total_phases} 成功"
    )
    print(f"  总命令数:      {result.total_commands}")
    print()

    for phase in result.phase_results:
        icon = "✓" if phase.success else "✗"
        print(
            f"  [{icon}] Phase {phase.phase_number}: "
            f"{phase.phase_name} — {phase.message} "
            f"({phase.commands_executed} cmds)"
        )

    if result.third_party_packages:
        print()
        print(
            f"  第三方应用 ({len(result.third_party_packages)}):"
        )
        for pkg in result.third_party_packages:
            print(f"    • {pkg}")

    print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数
        2. 配置日志
        3. 检测设备序列号
        4. 执行 change_location_only()
        5. 输出结果
    """
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(
        args.adb_path
    )

    try:
        result = change_location_only(
            adb_path=args.adb_path,
            serial=serial,
            profile_name=args.profile,
        )
    except AdbError as exc:
        log.error("Change Location Only 失败: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
