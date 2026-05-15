"""
XML 文件修改器。

严格基于 pull/push 文件差异分析实现。

==============================================================
packages.xml 差异（pcapng 命令 297-298）：
    1. com.android.vending: ft/it/ut 时间戳统一为 touch 时间
    2. com.google.android.gms: ft/it/ut 时间戳统一为 touch 时间
    ⚠ <version> 标签的 fingerprint/sdkVersion 未修改

settings_global.xml 差异（pcapng 命令 310-312）：
    1. device_name: value/defaultValue → profile.model
    2. wifi_on: package → "android"
    3. development_settings_enabled: package → "com.android.settings"
    4. 删除 <namespaceHashes />

settings_secure.xml 差异（pcapng 命令 313-315）：
    1. android_id: value/defaultValue → profile.android_id
    2. lockscreen.disabled: value/defaultValue → "1"
    3. 删除 <namespaceHashes />
==============================================================

使用 Python 官方标准库 xml.etree.ElementTree。

参考：
- https://docs.python.org/3/library/xml.etree.elementtree.html
- https://docs.python.org/3/library/tempfile.html
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from michanger.common import AdbExecutor
from michanger.common import DeviceProfile

logger = logging.getLogger(__name__)

# 设备端 XML 文件路径
_PACKAGES_XML: str = "/data/system/packages.xml"
_SETTINGS_GLOBAL_XML: str = "/data/system/users/0/settings_global.xml"
_SETTINGS_SECURE_XML: str = "/data/system/users/0/settings_secure.xml"

# 系统文件 touch 路径（pcapng 命令 299-304）
_TOUCH_TARGETS: tuple[str, ...] = (
    "./system/priv-app/Phonesky",
    "./system/priv-app/Phonesky/Phonesky.apk",
    "./system/priv-app/PrebuiltGmsCorePi",
    "./system/priv-app/PrebuiltGmsCorePi/PrebuiltGmsCorePi.apk",
    "./system/priv-app/GoogleServicesFramework",
    "./system/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk",
)

# 额外清理路径（pcapng 命令 305-309）
_EXTRA_CLEANUP_PATHS: tuple[str, ...] = (
    "/system/addon.d",
    "/system/bin/install-recovery.sh",
    "/vendor/bin/install-recovery.sh",
    "/sdcard/TWRP",
)

# packages.xml 中需要统一时间戳的包名
_PACKAGES_TIMESTAMP_TARGETS: tuple[str, ...] = (
    "com.android.vending",
    "com.google.android.gms",
)


# ------------------------------------------------------------------
# packages.xml 修改
#
# 差异分析结果：
#   - com.android.vending: ft/it/ut 统一为 touch 时间戳
#   - com.google.android.gms: ft/it/ut 统一为 touch 时间戳
#   - <version> 标签不修改
# ------------------------------------------------------------------

def _modify_packages_xml(
    tree: ET.ElementTree,
    profile: DeviceProfile,
) -> None:
    """修改 packages.xml 中的包时间戳。

    基于 pull/push 差异分析：
    - com.android.vending 和 com.google.android.gms 的
      ft, it, ut 属性统一设为当前时间戳（十六进制毫秒）
    - <version> 标签的 fingerprint/sdkVersion 不做修改
    """
    root = tree.getroot()

    # 生成当前时间的十六进制毫秒时间戳
    now_hex = format(int(time.time() * 1000), "x")

    for pkg_elem in root.findall("package"):
        name = pkg_elem.get("name", "")
        if name in _PACKAGES_TIMESTAMP_TARGETS:
            old_ft = pkg_elem.get("ft", "")
            old_it = pkg_elem.get("it", "")
            old_ut = pkg_elem.get("ut", "")

            pkg_elem.set("ft", now_hex)
            pkg_elem.set("it", now_hex)
            pkg_elem.set("ut", now_hex)

            logger.debug(
                "packages.xml %s: ft=%s→%s, it=%s→%s, ut=%s→%s",
                name, old_ft, now_hex, old_it, now_hex, old_ut, now_hex,
            )


# ------------------------------------------------------------------
# settings_global.xml 修改
#
# 差异分析结果：
#   - device_name: value + defaultValue → profile.model
#   - wifi_on: package → "android"
#   - development_settings_enabled: package → "com.android.settings"
#   - 删除尾部 <namespaceHashes />
# ------------------------------------------------------------------

def _modify_settings_global_xml(
    tree: ET.ElementTree,
    profile: DeviceProfile,
) -> None:
    """修改 settings_global.xml。

    基于 pull/push 差异分析严格实现。
    """
    root = tree.getroot()

    for setting in root.iter("setting"):
        name = setting.get("name", "")

        if name == "device_name":
            # value 和 defaultValue 都改为目标 model
            setting.set("value", profile.model)
            setting.set("defaultValue", profile.model)
            logger.debug("settings_global device_name → %s", profile.model)

        elif name == "wifi_on":
            # package 从 "com.android.shell" 改为 "android"
            setting.set("package", "android")
            logger.debug("settings_global wifi_on package → android")

        elif name == "development_settings_enabled":
            # package 从 "com.android.shell" 改为 "com.android.settings"
            setting.set("package", "com.android.settings")
            logger.debug(
                "settings_global development_settings_enabled "
                "package → com.android.settings"
            )

    # 删除 <namespaceHashes> 子元素（如果存在）
    ns_elem = root.find("namespaceHashes")
    if ns_elem is not None:
        root.remove(ns_elem)
        logger.debug("settings_global 删除 <namespaceHashes>")


# ------------------------------------------------------------------
# settings_secure.xml 修改
#
# 差异分析结果：
#   - android_id: value + defaultValue → profile.android_id
#   - lockscreen.disabled: value + defaultValue → "1"
#   - 删除尾部 <namespaceHashes />
# ------------------------------------------------------------------

def _modify_settings_secure_xml(
    tree: ET.ElementTree,
    profile: DeviceProfile,
) -> None:
    """修改 settings_secure.xml。

    基于 pull/push 差异分析严格实现。
    """
    root = tree.getroot()

    for setting in root.iter("setting"):
        name = setting.get("name", "")

        if name == "android_id":
            # value 和 defaultValue 都改为目标 android_id
            old_val = setting.get("value", "")
            setting.set("value", profile.android_id)
            setting.set("defaultValue", profile.android_id)
            logger.debug(
                "settings_secure android_id: %s → %s",
                old_val, profile.android_id,
            )

        elif name == "lockscreen.disabled":
            # value 和 defaultValue 都改为 "1"
            setting.set("value", "1")
            setting.set("defaultValue", "1")
            logger.debug("settings_secure lockscreen.disabled → 1")

    # 删除 <namespaceHashes>
    ns_elem = root.find("namespaceHashes")
    if ns_elem is not None:
        root.remove(ns_elem)
        logger.debug("settings_secure 删除 <namespaceHashes>")


# ------------------------------------------------------------------
# 通用 pull → modify → push
# ------------------------------------------------------------------

def _pull_modify_push(
    adb: AdbExecutor,
    remote_path: str,
    modifier_fn: object,
    profile: DeviceProfile,
    work_dir: Path,
) -> int:
    """pull → 修改 → push 单个 XML 文件。

    注意：settings 文件可能在 root 标签后有 <namespaceHashes />，
    这会导致 ET.parse() 失败。需要在解析前清理。

    Returns:
        执行的命令数量
    """
    count = 0
    filename = Path(remote_path).name
    local_path = work_dir / filename

    # Pull
    pull_result = adb.pull(remote_path, local_path)
    count += 1
    if not pull_result.success:
        logger.error("拉取 %s 失败: %s", remote_path, pull_result.output)
        return count

    # Parse & Modify
    try:
        # 预处理：删除 root 标签外的 <namespaceHashes />
        raw = local_path.read_text(encoding="utf-8")
        cleaned = re.sub(
            r"</settings>\s*<namespaceHashes\s*/>",
            "</settings>",
            raw,
        )
        local_path.write_text(cleaned, encoding="utf-8")

        tree = ET.parse(local_path)
        modifier_fn(tree, profile)  # type: ignore[operator]

        tree.write(
            local_path,
            encoding="utf-8",
            xml_declaration=True,
        )
        logger.info("本地修改 %s 完成", filename)
    except ET.ParseError as exc:
        logger.error("XML 解析失败 %s: %s", filename, exc)
        return count

    # Push
    push_result = adb.push(local_path, remote_path)
    count += 1
    if not push_result.success:
        logger.error("推送 %s 失败: %s", remote_path, push_result.output)

    return count


# ------------------------------------------------------------------
# 公共 API — 严格按 pcapng 命令 297-317 顺序执行
# ------------------------------------------------------------------

def modify_xml_files(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """执行 XML 文件处理及穿插的 touch/rm-rf/restorecon。

    严格按 pcapng 命令 297-317 的精确顺序：
    297-298: packages.xml pull/push
    299-304: touch 系统 APK
    305-309: rm -rf 额外清理
    310-312: settings_global.xml pull/push/restorecon
    313-315: settings_secure.xml pull/push/restorecon
    316-317: restorecon /data/system + providers.settings

    Args:
        adb: ADB 执行器
        profile: 设备配置

    Returns:
        执行的命令数量
    """
    count = 0

    with tempfile.TemporaryDirectory(prefix="michanger_xml_") as tmp:
        work_dir = Path(tmp)

        # ---- pcapng 命令 297-298: packages.xml pull/push ----
        logger.info("处理 packages.xml ...")
        count += _pull_modify_push(
            adb, _PACKAGES_XML,
            _modify_packages_xml, profile, work_dir,
        )

        # ---- pcapng 命令 299-304: touch 系统 APK 时间戳 ----
        for target in _TOUCH_TARGETS:
            adb.shell(f"find {target} -exec touch -m -a {{}} +")
            count += 1

        # ---- pcapng 命令 316: rm -rf extra_cleanup_packages 数据 ----
        # 仅清理额外配置的包（如 subscriptions.red）
        # 固定包的 rm-rf 已在阶段 9 完成
        _APP_DATA_DIR_TEMPLATES = (
            "/data/data/{pkg}",
            "/data/user_de/0/{pkg}",
            "/data/user/0/{pkg}",
            "/sdcard/Android/data/{pkg}",
            "/data/misc/profiles/ref/{pkg}",
            "/data/misc/profiles/cur/0/{pkg}",
        )
        for pkg in profile.extra_cleanup_packages:
            paths = " ".join(
                tpl.format(pkg=pkg) for tpl in _APP_DATA_DIR_TEMPLATES
            )
            adb.shell(f"rm -rf {paths}")
            count += 1

        # ---- pcapng 命令 317-320: rm -rf 额外清理 ----
        for path in _EXTRA_CLEANUP_PATHS:
            adb.shell(f"rm -rf {path}")
            count += 1

        # ---- pcapng 命令 310-311: settings_global.xml pull/push ----
        logger.info("处理 settings_global.xml ...")
        count += _pull_modify_push(
            adb, _SETTINGS_GLOBAL_XML,
            _modify_settings_global_xml, profile, work_dir,
        )

        # ---- pcapng 命令 312: restorecon settings_global.xml ----
        adb.shell(
            "restorecon -Rv /data/system/users/0/settings_global.xml"
        )
        count += 1

        # ---- pcapng 命令 313-314: settings_secure.xml pull/push ----
        logger.info("处理 settings_secure.xml ...")
        count += _pull_modify_push(
            adb, _SETTINGS_SECURE_XML,
            _modify_settings_secure_xml, profile, work_dir,
        )

        # ---- pcapng 命令 315: restorecon settings_secure.xml ----
        adb.shell(
            "restorecon -Rv /data/system/users/0/settings_secure.xml"
        )
        count += 1

    # ---- pcapng 命令 316: restorecon /data/system ----
    adb.shell("restorecon -Rv /data/system")
    count += 1

    # ---- pcapng 命令 317: restorecon providers.settings ----
    adb.shell(
        "restorecon -Rv /data/data/com.android.providers.settings/*"
    )
    count += 1

    return count
