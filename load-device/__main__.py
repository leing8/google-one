"""
Load Device CLI 入口。

支持 python -m load-device 运行。
列出所有已连接的 ADB 设备，并对每台在线设备执行完整探测。

用法：
    python -m load-device [--adb-path PATH] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .load_device import load_all_devices
from .models import LoadDeviceResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent / "platform-tools" / "adb.exe"
)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="load-device",
        description="Load Device — 列出并探测所有已连接的 Android 设备",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m load-device\n"
            "  python -m load-device --adb-path C:\\tools\\adb.exe\n"
            "  python -m load-device -v\n"
        ),
    )
    parser.add_argument(
        "--adb-path",
        type=Path,
        default=_DEFAULT_ADB_PATH,
        help=f"adb 可执行文件路径（默认：{_DEFAULT_ADB_PATH}）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志（DEBUG 级别）",
    )
    return parser


def _setup_logging(*, verbose: bool) -> None:
    """配置日志系统。

    Args:
        verbose: 是否启用 DEBUG 级别日志
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _print_device(index: int, result: LoadDeviceResult) -> None:
    """打印单台设备的探测结果。

    使用 key-value 对齐格式，简洁清晰。
    非在线设备仅显示序列号和状态。

    Args:
        index: 设备序号（从 1 开始）
        result: 单台设备的探测结果
    """
    is_online = result.state == "device"

    print(f"[Device {index}]")
    print(f"  Serial:          {result.serial}")
    print(f"  State:           {result.state}")

    if not is_online:
        print()
        return

    props = result.properties
    print(f"  Brand:           {props.brand}")
    print(f"  Model:           {props.model}")
    print(f"  Android:         {props.android_version}")

    mi = result.michanger
    print(f"  MiChanger:       {mi.rom_version or 'N/A'}")
    print(f"  Config Path:     {mi.config_path or 'N/A'}")

    pkg_count = len(result.third_party_packages)
    print(f"  3rd Party Apps:  {pkg_count}")

    if result.third_party_packages:
        for pkg in result.third_party_packages:
            print(f"    - {pkg}")

    print()


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    log = logging.getLogger(__name__)

    try:
        results = load_all_devices(adb_path=args.adb_path)
    except Exception as exc:
        log.error("Load Device 失败: %s", exc)
        sys.exit(1)

    if not results:
        print("No devices connected.")
        sys.exit(0)

    print()
    for i, result in enumerate(results, start=1):
        _print_device(i, result)


if __name__ == "__main__":
    main()
