"""
Import File to Phone CLI 入口。

支持 python -m michanger.import_file_to_phone 运行。
将本地文件推送到设备 /sdcard/ 并触发媒体扫描。

用法：
    python -m michanger.import_file_to_phone
    python -m michanger.import_file_to_phone -s SERIAL_NUMBER -v
    python -m michanger.import_file_to_phone --push-dir /path/to/files

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
from .import_file_to_phone import import_files
from .models import ImportResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
# michanger/import_file_to_phone/__main__.py → 3 级 parent 到项目根
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent / "platform-tools" / "adb.exe"
)

# 默认推送文件目录：模块包内的 push/ 子目录
_DEFAULT_PUSH_DIR: Path = (
    Path(__file__).resolve().parent / "push"
)

# 设备端目标目录（与 pcapng 一致）
_DEFAULT_REMOTE_DIR: str = "/sdcard"


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    遵循 Python argparse 官方最佳实践：
    - 使用 prog 指定程序名
    - 使用 type=Path 自动转换路径参数
    - 提供 epilog 示例用法

    参考：https://docs.python.org/3/library/argparse.html

    Returns:
        配置完成的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="michanger.import_file_to_phone",
        description=(
            "Import File to Phone — "
            "文件推送与媒体扫描"
            "（严格还原 13.0-Import File to Phone.pcapng）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.import_file_to_phone\n"
            "  python -m michanger.import_file_to_phone -s SERIAL_NUMBER\n"
            "  python -m michanger.import_file_to_phone --push-dir ./my_files\n"
            "  python -m michanger.import_file_to_phone -v\n"
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
        "--push-dir",
        type=Path,
        default=_DEFAULT_PUSH_DIR,
        help=f"本地推送文件目录（默认：{_DEFAULT_PUSH_DIR}）",
    )
    parser.add_argument(
        "--remote-dir",
        type=str,
        default=_DEFAULT_REMOTE_DIR,
        help=f"设备端目标目录（默认：{_DEFAULT_REMOTE_DIR}）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _print_result(result: ImportResult) -> None:
    """打印导入结果。

    Args:
        result: 文件导入结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  Import File to Phone 结果: {status}")
    print("=" * 60)
    print(f"  设备序列号:     {result.serial}")
    print(
        f"  文件推送:       "
        f"{result.success_count}/{result.total_files} 成功"
        f" ({result.total_size_bytes / 1024:.2f} KB)"
    )
    print(
        f"  媒体卷扫描:     "
        f"{'成功' if result.media_scan_success else '失败'}"
    )
    print(
        f"  媒体扫描广播:   "
        f"{'成功' if result.media_broadcast_success else '失败'}"
    )
    print()

    # 逐个文件的传输状态
    if result.file_results:
        print("  文件详情:")
        for r in result.file_results:
            icon = "✓" if r.success else "✗"
            size_kb = r.file_info.size_bytes / 1024
            print(
                f"    {icon} {r.file_info.name}"
                f" ({size_kb:.1f} KB)"
                f" → {r.file_info.remote_path}"
            )
            if not r.success:
                print(f"      错误: {r.message}")
        print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数
        2. 配置日志
        3. 验证推送目录
        4. 检测设备序列号
        5. 执行 import_files()
        6. 输出结果
    """
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    # 验证推送目录存在
    push_dir: Path = args.push_dir
    if not push_dir.is_dir():
        print(
            f"错误：推送目录不存在：{push_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 验证目录中有文件
    file_count = sum(1 for f in push_dir.iterdir() if f.is_file())
    if file_count == 0:
        print(
            f"错误：推送目录为空：{push_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 自动检测或使用指定的序列号
    serial: str = args.serial or auto_detect_serial(args.adb_path)

    try:
        result = import_files(
            adb_path=args.adb_path,
            serial=serial,
            push_dir=push_dir,
            remote_dir=args.remote_dir,
        )
    except AdbError as exc:
        log.error("Import File to Phone 失败: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
