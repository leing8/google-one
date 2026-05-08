"""Randomly Change Device — XML 文件修改工具.

从设备 pull XML 文件，使用 Python 标准库 xml.etree.ElementTree 修改后
push 回设备。严格按照抓包日志中的差异进行修改。

处理的 XML 文件：
    1. packages.xml — 更新 vending/gms 包的 ft/ut/it 时间戳
    2. settings_global.xml — 修改 device_name、package 归属等
    3. settings_secure.xml — 修改 lockscreen.disabled、android_id 等

Python 官方最佳实践：
    - xml.etree.ElementTree 是推荐的 XML 处理库
    - tempfile 模块用于安全的临时文件操作
    - pathlib.Path 用于路径操作

参考:
    https://docs.python.org/3/library/xml.etree.elementtree.html
    https://docs.python.org/3/library/tempfile.html
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from adb_executor import AdbExecutor

logger = logging.getLogger(__name__)

_SHELL_TIMEOUT: int = 30
_PULL_TIMEOUT: int = 60
_PUSH_TIMEOUT: int = 60


def _pull_file(
    executor: AdbExecutor,
    remote_path: str,
    local_path: Path,
) -> bool:
    """从设备 pull 文件到本地。"""
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
    """推送本地文件到设备。"""
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
    """解析 XML 文件，处理 BOM 编码。

    Python 官方推荐: 使用 ET.parse() 解析文件。
    """
    return ET.parse(filepath, parser=ET.XMLParser(encoding="utf-8"))


def _write_xml(tree: ET.ElementTree, filepath: Path) -> None:
    """写入 XML 文件。

    使用 xml_declaration=True 生成 XML 声明头。
    使用 ET.indent() 设置 2 空格缩进（Python 3.9+）。
    """
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
    """在 settings XML 中查找指定 name 的 setting 元素。"""
    for setting in root.iter("setting"):
        if setting.get("name") == name:
            return setting
    return None


def _remove_namespace_hashes(filepath: Path) -> None:
    """移除 XML 文件末尾的 <namespaceHashes /> 标签。

    抓包日志中 push 版本均移除了此标签。
    使用文本处理而非 XML 解析，因为该标签可能在根元素之外。
    """
    content = filepath.read_text(encoding="utf-8")
    # 移除 <namespaceHashes /> 或 <namespaceHashes/> 行
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
    """修改 packages.xml 文件。

    从设备 pull → 修改 → push 回设备。

    修改内容（基于抓包日志 pull/push 差异分析）:
    1. com.android.vending 包: 更新 ft/ut/it 时间戳为统一值
    2. com.google.android.gms 包: 更新 ft/ut/it 时间戳为统一值

    ft/ut/it 均设置为相同的当前时间戳（十六进制毫秒）。

    参数:
        executor: ADB 执行器。
        work_dir: 本地工作目录。

    返回:
        是否成功。
    """
    remote_path = "/data/system/packages.xml"
    local_path = work_dir / "packages.xml"

    # Pull
    if not _pull_file(executor, remote_path, local_path):
        return False

    # 修改
    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        # 生成统一时间戳（十六进制毫秒）
        ts_hex = format(int(time.time() * 1000), "x")
        logger.info("  统一时间戳: %s", ts_hex)

        # 更新 com.android.vending 和 com.google.android.gms
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

        # 写入（ET 默认使用双引号和 2 空格缩进，与抓包日志一致）
        _write_xml(tree, local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    # Push
    return _push_file(executor, local_path, remote_path)


# ── settings_global.xml 修改 ────────────────────────────────────


def modify_settings_global_xml(
    executor: AdbExecutor,
    work_dir: Path,
    device_name: str,
) -> bool:
    """修改 settings_global.xml 文件。

    修改内容（基于抓包日志 pull/push 差异分析）:
    1. device_name: 旧值 → 新设备名称（例如 "Pixel 10 Pro"）
    2. development_settings_enabled: package 从 com.android.shell → com.android.settings
    3. wifi_on: package 从 com.android.shell → android
    4. 移除 <namespaceHashes /> 标签

    参数:
        executor: ADB 执行器。
        work_dir: 本地工作目录。
        device_name: 新设备名称。

    返回:
        是否成功。
    """
    remote_path = "/data/system/users/0/settings_global.xml"
    local_path = work_dir / "settings_global.xml"

    # Pull
    if not _pull_file(executor, remote_path, local_path):
        return False

    # 修改
    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        # 1. 修改 device_name
        elem = _find_setting(root, "device_name")
        if elem is not None:
            old_name = elem.get("value", "")
            elem.set("value", device_name)
            elem.set("defaultValue", device_name)
            logger.info(
                "  device_name: %s → %s", old_name, device_name,
            )

        # 2. 修改 development_settings_enabled 的 package
        elem = _find_setting(root, "development_settings_enabled")
        if elem is not None:
            elem.set("package", "com.android.settings")
            logger.info(
                "  development_settings_enabled: package → com.android.settings",
            )

        # 3. 修改 wifi_on 的 package
        elem = _find_setting(root, "wifi_on")
        if elem is not None:
            elem.set("package", "android")
            logger.info("  wifi_on: package → android")

        # 写入
        _write_xml(tree, local_path)

        # 4. 移除 namespaceHashes
        _remove_namespace_hashes(local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    # Push
    return _push_file(executor, local_path, remote_path)


# ── settings_secure.xml 修改 ────────────────────────────────────


def modify_settings_secure_xml(
    executor: AdbExecutor,
    work_dir: Path,
    android_id: str,
) -> bool:
    """修改 settings_secure.xml 文件。

    修改内容（基于抓包日志 pull/push 差异分析）:
    1. lockscreen.disabled: value 0 → 1, defaultValue 0 → 1
    2. android_id: 旧值 → 新的随机 ID
    3. 移除 <namespaceHashes /> 标签

    参数:
        executor: ADB 执行器。
        work_dir: 本地工作目录。
        android_id: 新的 android_id 值。

    返回:
        是否成功。
    """
    remote_path = "/data/system/users/0/settings_secure.xml"
    local_path = work_dir / "settings_secure.xml"

    # Pull
    if not _pull_file(executor, remote_path, local_path):
        return False

    # 修改
    try:
        tree = _parse_xml(local_path)
        root = tree.getroot()

        # 1. 修改 lockscreen.disabled
        elem = _find_setting(root, "lockscreen.disabled")
        if elem is not None:
            elem.set("value", "1")
            elem.set("defaultValue", "1")
            logger.info("  lockscreen.disabled: → 1")

        # 2. 修改 android_id
        elem = _find_setting(root, "android_id")
        if elem is not None:
            old_id = elem.get("value", "")
            elem.set("value", android_id)
            elem.set("defaultValue", android_id)
            logger.info("  android_id: %s → %s", old_id, android_id)

        # 写入
        _write_xml(tree, local_path)

        # 3. 移除 namespaceHashes
        _remove_namespace_hashes(local_path)

    except ET.ParseError as e:
        logger.error("  XML 解析失败: %s", e)
        return False

    # Push
    return _push_file(executor, local_path, remote_path)
