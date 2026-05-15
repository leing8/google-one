"""
Wipe Packages & Reboot CLI 入口。

支持 python -m michanger.wipe_packages_reboot 运行。
执行包清理、Recovery 深度清理、packages.xml 修改和设备重启。

额外清理包通过配置文件 wipe_config.json 管理。

用法：
    python -m michanger.wipe_packages_reboot
    python -m michanger.wipe_packages_reboot -s SERIAL_NUMBER -v

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
from .models import WipeResult
from .wipe_packages_reboot import load_config, wipe_packages_and_reboot

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/wipe_packages_reboot/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    Returns:
        配置完成的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="michanger.wipe_packages_reboot",
        description=(
            "Wipe Packages & Reboot — "
            "包清理、Recovery 深度清理、packages.xml 修改和设备重启"
            "（严格还原 11.0-Wipe Packages & Reboot.pcapng）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "额外清理包通过 wipe_config.json 配置：\n"
            '  {\n'
            '    "extra_cleanup_packages": [\n'
            '      "com.google.android.apps.subscriptions.red",\n'
            '      "gr.nikolasspyr.integritycheck"\n'
            '    ]\n'
            '  }\n'
            "\n"
            "示例：\n"
            "  python -m michanger.wipe_packages_reboot\n"
            "  python -m michanger.wipe_packages_reboot -s SERIAL_NUMBER\n"
            "  python -m michanger.wipe_packages_reboot -v\n"
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=_DEFAULT_ADB_PATH,
        help=f"adb 可执行文件路径（默认：{_DEFAULT_ADB_PATH}）",
    )
    parser.add_argument(
        "-s", "--serial",
        type=str,
        default=None,
        help="设备序列号（默认：自动检测第一台在线设备）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _print_result(result: WipeResult) -> None:
    """打印执行结果。"""
    print()
    print("[Wipe Packages & Reboot Result]")
    print(f"  Serial:          {result.serial}")
    print(f"  Overall Success: {result.success}")
    print(f"  Total Phases:    {result.success_count}/{result.total_phases}")
    print(f"  Total Commands:  {result.total_commands}")
    print()

    for phase in result.phase_results:
        status = "✓" if phase.success else "✗"
        print(
            f"  [{status}] Phase {phase.phase_number}: "
            f"{phase.phase_name} — {phase.message} "
            f"({phase.commands_executed} cmds)"
        )

    print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数
        2. 配置日志
        3. 从 wipe_config.json 加载配置
        4. 检测设备序列号
        5. 执行 wipe_packages_and_reboot()
        6. 输出结果
    """
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 从 wipe_config.json 加载配置
    config = load_config()

    # 自动检测设备序列号
    serial = args.serial
    if serial is None:
        serial = auto_detect_serial(adb_path=args.adb_path)

    try:
        result = wipe_packages_and_reboot(
            adb_path=args.adb_path,
            serial=serial,
            config=config,
        )
    except AdbError as exc:
        log.error("Wipe Packages & Reboot 失败: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
