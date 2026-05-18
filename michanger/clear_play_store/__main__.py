"""
Clear Google Play Store CLI 入口。

支持 python -m michanger.clear_play_store 运行。
清除 Google Play Store 的应用数据。

用法：
    python -m michanger.clear_play_store
    python -m michanger.clear_play_store -s SERIAL_NUMBER
    python -m michanger.clear_play_store -v

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
from .clear_play_store import clear_play_store
from .models import ClearPlayStoreResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
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
        prog="michanger.clear_play_store",
        description=(
            "Clear Google Play Store — "
            "清除 Play Store 数据"
            "（严格还原 18.0-Clear Google Play Store.pcapng）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.clear_play_store\n"
            "  python -m michanger.clear_play_store"
            " -s SERIAL_NUMBER\n"
            "  python -m michanger.clear_play_store -v\n"
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
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _print_result(result: ClearPlayStoreResult) -> None:
    """打印执行结果。

    Args:
        result: Play Store 清除结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  Clear Google Play Store 结果: {status}")
    print("=" * 60)
    print(f"  设备序列号:    {result.serial}")
    print(f"  pm clear 输出: {result.pm_clear_output}")
    print(
        f"  清除结果:      "
        f"{'成功' if result.clear_success else '失败'}"
    )
    print(f"  总命令数:      {result.commands_executed}")
    print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数
        2. 配置日志
        3. 检测设备序列号
        4. 执行 clear_play_store()
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
        result = clear_play_store(
            adb_path=args.adb_path,
            serial=serial,
        )
    except AdbError as exc:
        log.error("Clear Google Play Store 失败: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
