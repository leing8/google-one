"""
Reboot CLI 入口。

支持 python -m michanger.reboot 运行。
向指定设备发送 adb reboot 命令执行正常重启。

用法：
    python -m michanger.reboot [--adb-path PATH] [-s SERIAL] [-v]

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
from .models import RebootResult
from .reboot import reboot_device

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/reboot/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践：
    - 使用 ArgumentParser 构建结构化 CLI
    - type=Path 自动转换路径参数
    - formatter_class=RawDescriptionHelpFormatter 保留 epilog 格式

    Returns:
        配置完成的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="michanger.reboot",
        description="Reboot — 向 Android 设备发送重启命令（严格还原 9.0-Reboot.pcapng）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m michanger.reboot\n"
            "  python -m michanger.reboot -s SERIAL_NUMBER\n"
            "  python -m michanger.reboot --adb-path C:\\tools\\adb.exe\n"
            "  python -m michanger.reboot -v\n"
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


def _print_result(result: RebootResult) -> None:
    """打印重启操作结果。

    使用 key-value 对齐格式，与其他模块（load_device 等）保持一致。

    Args:
        result: 重启操作结果
    """
    print()
    print("[Reboot Result]")
    print(f"  Serial:      {result.serial}")
    print(f"  Success:     {result.success}")
    print(f"  Command:     {result.command}")

    if result.stdout:
        print(f"  Stdout:      {result.stdout}")
    if result.stderr:
        print(f"  Stderr:      {result.stderr}")

    print(f"  Return Code: {result.returncode}")
    print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数（argparse）
        2. 配置日志系统（logging.basicConfig → stderr）
        3. 检测/验证设备序列号
        4. 执行 reboot_device()
        5. 输出结果并设置退出码
    """
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 自动检测设备序列号（如未指定）
    serial = args.serial
    if serial is None:
        serial = auto_detect_serial(adb_path=args.adb_path)

    try:
        result = reboot_device(
            adb_path=args.adb_path,
            serial=serial,
        )
    except AdbError as exc:
        log.error("Reboot 失败: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
