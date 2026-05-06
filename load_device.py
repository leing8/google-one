"""
Load Device — 加载并收集 Android 设备信息。

通过 ADB 执行一系列 shell 命令，收集设备的 MI Tool 状态、
配置路径、硬件信息和已安装应用。

命令行用法::

    python load_device.py
    python load_device.py --serial SERIAL_NUMBER
    python load_device.py --adb-path /path/to/adb

模块用法::

    from load_device import DeviceLoader, DeviceInfo
    from adb_client import AdbClient

    client = AdbClient(serial="SERIAL_NUMBER")
    loader = DeviceLoader(client)
    info: DeviceInfo = loader.load()

    print(info.brand)               # "google"
    print(info.to_dict())           # 完整字典
    print(info.to_json(indent=2))   # JSON 字符串
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from adb_client import AdbClient, AdbError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MI 配置目录候选路径（按抓包中的检查顺序）
# ---------------------------------------------------------------------------

_MI_CONFIG_CANDIDATES: tuple[str, ...] = (
    "/system/etc/mi",
    "/system/system/etc/mi",
    "/system_root/system/etc/mi",
    "/data/mi",
)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """设备信息数据类。

    存储 Load Device 流程中收集到的所有设备信息。
    提供 ``to_dict()`` 和 ``to_json()`` 方法，方便其他模块使用。

    Attributes:
        mi_tool_version: MI Tool 版本字符串（如 ``"michanger_4xl_11_v3"``），
            未安装时为 None。
        mi_config_path: MI 配置目录路径（如 ``"/system/etc/mi"``），
            未找到时为 None。
        brand: 设备品牌（如 ``"google"``）。
        model: 设备型号（如 ``"Pixel 4 XL"``）。
        android_version: Android 版本（如 ``"11"``）。
        third_party_packages: 第三方应用包名列表。
    """

    mi_tool_version: str | None = None
    mi_config_path: str | None = None
    brand: str = ""
    model: str = ""
    android_version: str = ""
    third_party_packages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，适合序列化和模块间传递。"""
        return {
            "mi_tool_version": self.mi_tool_version,
            "mi_config_path": self.mi_config_path,
            "brand": self.brand,
            "model": self.model,
            "android_version": self.android_version,
            "third_party_packages": self.third_party_packages,
        }

    def to_json(self, **kwargs: Any) -> str:
        """转换为 JSON 字符串。

        参数：
            **kwargs: 传递给 ``json.dumps()`` 的额外参数
                （如 ``indent=2``, ``ensure_ascii=False``）。
        """
        kwargs.setdefault("ensure_ascii", False)
        return json.dumps(self.to_dict(), **kwargs)

    def __str__(self) -> str:
        """人类可读的设备信息摘要。"""
        lines = [
            "=" * 50,
            "          Device Information",
            "=" * 50,
            f"  Brand:            {self.brand or 'N/A'}",
            f"  Model:            {self.model or 'N/A'}",
            f"  Android Version:  {self.android_version or 'N/A'}",
            f"  MI Tool Version:  {self.mi_tool_version or 'Not Installed'}",
            f"  MI Config Path:   {self.mi_config_path or 'Not Found'}",
            f"  3rd-Party Apps:   {len(self.third_party_packages)}",
        ]
        if self.third_party_packages:
            for pkg in self.third_party_packages:
                lines.append(f"    - {pkg}")
        lines.append("=" * 50)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 设备加载器
# ---------------------------------------------------------------------------

class DeviceLoader:
    """按抓包流程逐步加载设备信息。

    严格按照 Wireshark 抓包中 ``4.0-Load Device.txt`` 记录的
    命令顺序和逻辑执行，不因单步失败中断整体流程。

    参数：
        adb: AdbClient 实例。
    """

    def __init__(self, adb: AdbClient) -> None:
        self._adb = adb

    def load(self) -> DeviceInfo:
        """执行完整的设备加载流程。

        按抓包顺序依次执行：
        1. 检测 MI Tool（cat /system/bin/mi）
        2. 查找 MI 配置路径（ls 多个候选目录）
        3. 获取设备品牌（getprop ro.product.brand）
        4. 获取设备型号（getprop ro.product.model）
        5. 获取 Android 版本（getprop ro.build.version.release）
        6. 获取第三方应用列表（pm list packages -3）

        返回：
            DeviceInfo 对象，包含所有收集到的信息。
        """
        info = DeviceInfo()

        # Step 0: 检测 MI Tool
        info.mi_tool_version = self._detect_mi_tool()

        # Step 1-4: 查找 MI 配置路径
        info.mi_config_path = self._find_mi_config_path()

        # Step 5: 获取设备品牌
        info.brand = self._get_prop("ro.product.brand")

        # Step 6: 获取设备型号
        info.model = self._get_prop("ro.product.model")

        # Step 7: 获取 Android 版本
        info.android_version = self._get_prop("ro.build.version.release")

        # Step 8: 获取第三方应用列表
        info.third_party_packages = self._get_third_party_packages()

        return info

    # -- 私有方法：按抓包流程实现 --

    def _detect_mi_tool(self) -> str | None:
        """Step 0: 检测 MI Tool 版本。

        执行 ``cat /system/bin/mi``，解析返回的 ``rom.version=...`` 行。

        返回：
            MI Tool 版本字符串，或 None（未安装）。
        """
        logger.info("Step 0: 检测 MI Tool (cat /system/bin/mi)")
        result = self._adb.shell("cat /system/bin/mi")

        if not result.success or not result.output:
            logger.info("MI Tool 未安装")
            return None

        # 解析 "rom.version=michanger_4xl_11_v3" 格式
        for line in result.output.splitlines():
            line = line.strip()
            if line.startswith("rom.version="):
                version = line.split("=", 1)[1]
                logger.info("MI Tool 版本: %s", version)
                return version

        # 如果有输出但没有匹配的版本行，返回原始输出
        logger.info("MI Tool 输出: %s", result.output)
        return result.output

    def _find_mi_config_path(self) -> str | None:
        """Step 1-4: 在候选目录中查找 MI 配置路径。

        按抓包中记录的顺序依次检查每个候选路径，
        即使某个路径检查失败也继续检查下一个。

        返回：
            第一个存在的路径，或 None（全部不存在）。
        """
        for path in _MI_CONFIG_CANDIDATES:
            logger.info("检查 MI 配置路径: ls %s", path)
            result = self._adb.shell(f"ls {path}")

            if result.success and "No such file or directory" not in result.output:
                logger.info("找到 MI 配置路径: %s", path)
                return path

            logger.info("路径不存在: %s", path)

        logger.info("所有候选路径均不存在")
        return None

    def _get_prop(self, prop_name: str) -> str:
        """通过 getprop 获取设备属性值。

        参数：
            prop_name: 属性名（如 ``"ro.product.brand"``）。

        返回：
            属性值字符串，获取失败时返回空字符串。
        """
        logger.info("获取设备属性: getprop %s", prop_name)
        result = self._adb.shell(f"getprop {prop_name}")

        if result.success:
            value = result.output
            logger.info("%s = %s", prop_name, value)
            return value

        logger.warning("获取属性失败: %s", prop_name)
        return ""

    def _get_third_party_packages(self) -> list[str]:
        """Step 8: 获取第三方应用包名列表。

        执行 ``pm list packages -3``，解析每行 ``package:<包名>`` 格式。

        返回：
            包名列表（不含 ``package:`` 前缀），无应用时返回空列表。
        """
        logger.info("获取第三方应用列表: pm list packages -3")
        result = self._adb.shell("pm list packages -3")

        if not result.success or not result.output:
            logger.info("无第三方应用或命令失败")
            return []

        packages: list[str] = []
        for line in result.output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line[len("package:"):]
                packages.append(pkg)
            elif line:
                # 某些设备可能不带 "package:" 前缀
                packages.append(line)

        logger.info("第三方应用数量: %d", len(packages))
        return packages


# ---------------------------------------------------------------------------
# 控制台输出
# ---------------------------------------------------------------------------

def _print_device_info(info: DeviceInfo) -> None:
    """将设备信息以可读格式打印到控制台。"""
    print(info)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="load_device",
        description="Load Device — 加载 Android 设备信息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-s", "--serial",
        type=str,
        default=None,
        help="设备序列号（多设备时必须指定）",
    )
    parser.add_argument(
        "--adb-path",
        type=str,
        default=None,
        help="adb 可执行文件路径（默认自动查找）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="以 JSON 格式输出",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用详细日志输出",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> DeviceInfo:
    """Load Device 主函数。

    既可作为 CLI 入口使用，也可在其他模块中调用。

    参数：
        argv: 命令行参数列表。为 None 时使用 sys.argv。

    返回：
        DeviceInfo 对象。
    """
    args = _parse_args(argv)

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        # 创建 ADB 客户端
        adb = AdbClient(
            adb_path=args.adb_path,
            serial=args.serial,
        )

        # 加载设备信息
        loader = DeviceLoader(adb)
        info = loader.load()

        # 输出到控制台
        if args.output_json:
            print(info.to_json(indent=2))
        else:
            _print_device_info(info)

        return info

    except AdbError as exc:
        logger.error("ADB 错误: %s", exc)
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
