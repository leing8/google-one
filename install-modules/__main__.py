"""
Install Modules CLI 入口。

支持 python -m install-modules 运行。
批量安装 Magisk 模块。

用法：
    python -m install-modules [--adb-path PATH] [--serial SERIAL]
                              [--modules-dir DIR] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from common.adb_executor import AdbError, list_devices
from .install_modules import install_modules
from .models import InstallModulesResult

# 默认 adb 路径：项目根目录下的 platform-tools/adb.exe
_DEFAULT_ADB_PATH: Path = (
    Path(__file__).resolve().parent.parent / "platform-tools" / "adb.exe"
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
        prog="install-modules",
        description=(
            "Install Modules — "
            "批量安装 Magisk 模块（Zygisk、Shamiko、TrickyStore 等）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m install-modules\n"
            "  python -m install-modules --serial ABCD1234\n"
            "  python -m install-modules --modules-dir /path/to/modules\n"
            "  python -m install-modules --dry-run\n"
            "  python -m install-modules -v\n"
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


def _setup_logging(*, verbose: bool) -> None:
    """配置日志系统。

    遵循 Python logging 官方最佳实践：
    - 使用 logging.basicConfig() 进行简单配置
    - 日志输出到 stderr（不干扰 stdout 的结构化输出）
    - 使用 %-style 格式化（logging 推荐）

    参考：https://docs.python.org/3/howto/logging.html

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


def _auto_detect_serial(adb_path: Path) -> str:
    """自动检测第一台在线设备的序列号。

    Args:
        adb_path: adb 可执行文件路径

    Returns:
        设备序列号

    Raises:
        SystemExit: 无在线设备
    """
    devices = list_devices(adb_path=adb_path)

    if not devices:
        print("错误：未检测到已连接的 ADB 设备", file=sys.stderr)
        sys.exit(1)

    # 优先查找在线设备（state == "device"）
    online = [d for d in devices if d.is_online]
    if online:
        serial = online[0].serial
        print(f"自动检测到在线设备: {serial}", file=sys.stderr)
        return serial

    # 列出所有设备状态
    for device in devices:
        print(
            f"  设备 {device.serial}: {device.state}",
            file=sys.stderr,
        )
    print("错误：无在线设备", file=sys.stderr)
    sys.exit(1)


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

    _setup_logging(verbose=args.verbose)
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
    serial: str = args.serial or _auto_detect_serial(args.adb_path)

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
