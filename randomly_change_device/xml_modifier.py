"""Randomly Change Device — XML 文件修改工具.

从设备 pull XML 文件，使用 Python 标准库 xml.etree.ElementTree 修改后
push 回设备。严格按照抓包日志中的差异进行修改。

参考:
    https://docs.python.org/3/library/xml.etree.elementtree.html
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .adb_executor import AdbExecutor

logger = logging.getLogger(__name__)

_SHELL_TIMEOUT: int = 30
_PULL_TIMEOUT: int = 60
_PUSH_TIMEOUT: int = 60


def _pull_file(
    executor: AdbExecutor,
    remote_path: str,
    local_path: Path,
) -> bool:
    """从设备 pull 文件到本地."""
    logger.info("  Pull: %s → %s", remote_path, local_path)
    result = executor.run_command(
        "pull", remote_path, str(local_path),
        timeout=_PULL_TIMEOUT,
    )
    if result.success:
        logger.info("  Pull 成功")
    else:
        logger.error("  Pull 失败: %s", result.stderr)
    return result.success


def _push_file(
    executor: AdbExecutor,
    local_path: Path,
    remote_path: str,
) -> bool:
    """推送本地文件到设备."""
    logger.info("  Push: %s → %s", local_path, remote_path)
    result = executor.push(
        local_path=local_path,
        remote_path=remote_path,
        timeout=_PUSH_TIMEOUT,
    )
    if result.success:
        logger.info("  Push 成功")
    else:
        logger.error("  Push 失败: %s", result.stderr)
    return result.success


def _parse_xml(filepath: Path) -> ET.ElementTree:
    """解析 XML 文件."""
    return ET.parse(filepath, parser=ET.XMLParser(encoding="utf-8"))


def _write_xml(tree: ET.ElementTree, filepath: Path) -> None:
    """写入 XML 文件."""
    ET.indent(tree, space="  ")
    tree.write(
        filepath,
        encoding="utf-8",
        xml_declaration=True,
    )


def _find_setting(
    root: ET.Element,
    name: str,
) -> ET.Element | None:
    """在 settings XML 中查找指定 name 的 setting 元素."""
    for setting in root.iter("setting"):
        if setting.get("name") == name:
            return setting
    return None


def _remove_namespace_hashes(filepath: Path) -> None:
    """移除 XML 文件末尾的 <namespaceHashes /> 标签."""
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    filtered = [
        line for line in lines
        if "namespaceHashes" not in line
    ]
    filepath.write_text("".join(filtered), encoding="utf-8")


# ── packages.xml 修改 ───────────────────────────────────────────


def modify_packages_xml(
    executor: AdbExecutor,
    work_dir: Path,
) -> bool:
    """修改 packages.xml 文件.

    从设备 pull → 修改 → push 回设备。

    返回:
        是否成功。
    """
    remote_path = "/data/system/packages.xml"
    local_path = work_dir / "packages.xml"

    if not _pull_file(executor, remote_path, local_path):
        return False

    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        ts_hex = format(int(time.time() * 1000), "x")
        logger.info("  统一时间戳: %s", ts_hex)

        target_packages = ("com.android.vending", "com.google.android.gms")
        for pkg_name in target_packages:
            for pkg in root.iter("package"):
                if pkg.get("name") == pkg_name:
                    pkg.set("ft", ts_hex)
                    pkg.set("ut", ts_hex)
                    pkg.set("it", ts_hex)
                    logger.info(
                        "  已更新 %s: ft/ut/it=%s",
                        pkg_name, ts_hex,
                    )
                    break

        _write_xml(tree, local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    return _push_file(executor, local_path, remote_path)


# ── settings_global.xml 修改 ────────────────────────────────────


def modify_settings_global_xml(
    executor: AdbExecutor,
    work_dir: Path,
    device_name: str,
) -> bool:
    """修改 settings_global.xml 文件.

    返回:
        是否成功。
    """
    remote_path = "/data/system/users/0/settings_global.xml"
    local_path = work_dir / "settings_global.xml"

    if not _pull_file(executor, remote_path, local_path):
        return False

    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        elem = _find_setting(root, "device_name")
        if elem is not None:
            old_name = elem.get("value", "")
            elem.set("value", device_name)
            elem.set("defaultValue", device_name)
            logger.info(
                "  device_name: %s → %s", old_name, device_name,
            )

        elem = _find_setting(root, "development_settings_enabled")
        if elem is not None:
            elem.set("package", "com.android.settings")
            logger.info(
                "  development_settings_enabled: package → com.android.settings",
            )

        elem = _find_setting(root, "wifi_on")
        if elem is not None:
            elem.set("package", "android")
            logger.info("  wifi_on: package → android")

        _write_xml(tree, local_path)
        _remove_namespace_hashes(local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    return _push_file(executor, local_path, remote_path)


# ── settings_secure.xml 修改 ────────────────────────────────────


def modify_settings_secure_xml(
    executor: AdbExecutor,
    work_dir: Path,
    android_id: str,
) -> bool:
    """修改 settings_secure.xml 文件.

    返回:
        是否成功。
    """
    remote_path = "/data/system/users/0/settings_secure.xml"
    local_path = work_dir / "settings_secure.xml"

    if not _pull_file(executor, remote_path, local_path):
        return False

    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        elem = _find_setting(root, "lockscreen.disabled")
        if elem is not None:
            elem.set("value", "1")
            elem.set("defaultValue", "1")
            logger.info("  lockscreen.disabled: → 1")

        elem = _find_setting(root, "android_id")
        if elem is not None:
            old_id = elem.get("value", "")
            elem.set("value", android_id)
            elem.set("defaultValue", android_id)
            logger.info("  android_id: %s → %s", old_id, android_id)

        _write_xml(tree, local_path)
        _remove_namespace_hashes(local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    return _push_file(executor, local_path, remote_path)
