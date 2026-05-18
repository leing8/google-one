"""
Config Proxy CLI 入口。

支持 python -m michanger.config_proxy 运行。
读取当前代理并设置新的 HTTP 代理。

用法：
    python -m michanger.config_proxy 192.168.31.182:10808
    python -m michanger.config_proxy 192.168.31.72:7890 -s SERIAL
    python -m michanger.config_proxy 10.0.0.1:8080 -v

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
from .config_proxy import config_proxy
from .models import ConfigProxyResult

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
        prog="michanger.config_proxy",
        description=(
            "Config Proxy — "
            "设备 HTTP 代理配置"
            "（严格还原 16.0-Config Proxy.pcapng）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m michanger.config_proxy"
            " 192.168.31.182:10808\n"
            "  python -m michanger.config_proxy"
            " 192.168.31.72:7890 -s SERIAL\n"
            "  python -m michanger.config_proxy"
            " 10.0.0.1:8080 -v\n"
        ),
    )
    parser.add_argument(
        "proxy",
        type=str,
        help="代理地址（host:port 格式，如 192.168.31.182:10808）",
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


def _print_result(result: ConfigProxyResult) -> None:
    """打印执行结果。

    Args:
        result: 代理配置结果
    """
    status = "[OK]" if result.success else "[FAIL]"

    print()
    print("=" * 60)
    print(f"  Config Proxy 结果: {status}")
    print("=" * 60)
    print(f"  设备序列号:  {result.serial}")
    print(f"  之前的代理:  {result.previous_proxy}")
    print(f"  新设代理:    {result.new_proxy}")
    print(f"  设置结果:    {'成功' if result.set_success else '失败'}")
    print(f"  总命令数:    {result.commands_executed}")
    print()


def main() -> None:
    """CLI 主入口。

    流程：
        1. 解析命令行参数
        2. 配置日志
        3. 检测设备序列号
        4. 执行 config_proxy()
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
        result = config_proxy(
            adb_path=args.adb_path,
            serial=serial,
            proxy=args.proxy,
        )
    except AdbError as exc:
        log.error("Config Proxy 失败: %s", exc)
        sys.exit(1)
    except ValueError as exc:
        log.error("参数错误: %s", exc)
        sys.exit(1)

    _print_result(result)

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
