"""
XML Modifier — Android settings XML 配置文件修改工具。

对 Wireshark 抓包 ``7.0-Randomly change device.txt`` 中涉及的
三个 XML 配置文件进行不可变式读取、修改、写出。

使用 Python 标准库 ``xml.etree.ElementTree``（官方推荐的 XML 解析方式）。

抓包中的 XML 文件操作序列::

    1. adb pull /data/system/packages.xml                — 拉取（原样推回）
    2. adb pull /data/system/users/0/settings_global.xml — 拉取
       → 修改 device_name / development_settings_enabled / wifi_on
       → adb push 推回
    3. adb pull /data/system/users/0/settings_secure.xml — 拉取
       → 修改 android_id / lockscreen.disabled
       → adb push 推回
    4. restorecon -Rv 恢复 SELinux 上下文

注意：Android settings XML 在 ``</settings>`` 之后可能包含
``<namespaceHashes />``，此模块会自动预处理截断。

模块用法::

    from xml_modifier import modify_settings_global, modify_settings_secure
    from pathlib import Path

    modify_settings_global(
        Path("pull/settings_global.xml"),
        Path("push/settings_global.xml"),
        device_name="Pixel 10 Pro",
    )
"""

from __future__ import annotations

import logging
import secrets
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class XmlModification:
    """单条 XML setting 的修改描述。"""

    name: str
    field: str        # "value" or "defaultValue" or "package"
    new_value: str


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def generate_android_id() -> str:
    """生成 16 位随机十六进制 android_id。

    使用 secrets 模块保证密码学安全。

    Returns:
        16 位小写 hex 字符串, e.g. "eb16c2d6a12eb608"
    """
    return secrets.token_hex(8)


def read_settings_xml(filepath: Path) -> ET.ElementTree:
    """读取 Android settings XML 文件。

    Android settings XML 文件在 </settings> 之后可能包含
    <namespaceHashes /> 等额外内容，ElementTree 无法直接解析。
    此函数先预处理文本，截断到 </settings> 为止。

    Args:
        filepath: XML 文件路径

    Returns:
        解析后的 ElementTree

    Raises:
        FileNotFoundError: 文件不存在
        ET.ParseError: XML 格式错误
    """
    if not filepath.exists():
        raise FileNotFoundError(f"XML file not found: {filepath}")

    content = filepath.read_text(encoding="utf-8")

    # 截断 </settings> 之后的所有内容（如 <namespaceHashes />）
    end_tag = "</settings>"
    end_pos = content.find(end_tag)
    if end_pos >= 0:
        content = content[:end_pos + len(end_tag)] + "\n"

    return ET.ElementTree(ET.fromstring(content))


def modify_setting(
    root: ET.Element,
    name: str,
    *,
    value: str | None = None,
    default_value: str | None = None,
    package: str | None = None,
) -> bool:
    """修改 settings XML 中指定 name 的 setting 条目。

    不会修改原始 Element，而是在原位更新属性（ElementTree API 限制）。

    Args:
        root: XML 根元素
        name: setting 的 name 属性
        value: 新的 value（None 表示不修改）
        default_value: 新的 defaultValue（None 表示不修改）
        package: 新的 package（None 表示不修改）

    Returns:
        是否找到并修改了目标 setting
    """
    for elem in root.iter("setting"):
        if elem.get("name") == name:
            if value is not None:
                elem.set("value", value)
            if default_value is not None:
                elem.set("defaultValue", default_value)
            if package is not None:
                elem.set("package", package)
            logger.debug("Modified setting '%s'", name)
            return True

    logger.warning("Setting '%s' not found", name)
    return False


def remove_setting(root: ET.Element, name: str) -> bool:
    """从 settings XML 中删除指定 name 的 setting 条目。

    Args:
        root: XML 根元素（<settings>）
        name: 要删除的 setting 的 name 属性

    Returns:
        是否找到并删除了目标 setting
    """
    for elem in list(root):
        if elem.tag == "setting" and elem.get("name") == name:
            root.remove(elem)
            logger.debug("Removed setting '%s'", name)
            return True

    logger.warning("Setting '%s' not found for removal", name)
    return False


def remove_namespace_hashes(tree: ET.ElementTree) -> bool:
    """删除 XML 末尾的 <namespaceHashes /> 元素。

    Args:
        tree: ElementTree 对象

    Returns:
        是否找到并删除了 namespaceHashes
    """
    root = tree.getroot()
    # namespaceHashes 可能是 root 的兄弟节点
    # 但在 ElementTree 中，只有 root 的子元素可被管理
    # 实际上 namespaceHashes 出现在 </settings> 之后，
    # 需要通过文本处理来删除
    return False  # 由 write_settings_xml 中的文本后处理完成


def write_settings_xml(
    tree: ET.ElementTree,
    output_path: Path,
) -> None:
    """将修改后的 settings XML 写入文件。

    Args:
        tree: 修改后的 ElementTree
        output_path: 输出文件路径
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ET.indent(tree, space="  ")
    tree.write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

    # 后处理：删除 namespaceHashes 行
    content = output_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    filtered = [
        line for line in lines
        if "namespaceHashes" not in line
    ]
    output_path.write_text("".join(filtered), encoding="utf-8")

    logger.info("Written modified XML to %s", output_path)


# ---------------------------------------------------------------------------
# settings_global.xml 修改
# ---------------------------------------------------------------------------

def modify_settings_global(
    input_path: Path,
    output_path: Path,
    *,
    device_name: str,
) -> Path:
    """修改 settings_global.xml。

    从日志中提取的修改点：
    - device_name: 更新为新设备名
    - development_settings_enabled: package 改为 com.android.settings
    - wifi_on: package 改为 android

    Args:
        input_path: 原始 XML 路径
        output_path: 修改后的输出路径
        device_name: 新设备名称

    Returns:
        输出文件路径
    """
    tree = read_settings_xml(input_path)
    root = tree.getroot()

    # 修改 device_name
    modify_setting(
        root, "device_name",
        value=device_name,
        default_value=device_name,
    )

    # development_settings_enabled: package → com.android.settings
    modify_setting(
        root, "development_settings_enabled",
        package="com.android.settings",
    )

    # wifi_on: package → android
    modify_setting(root, "wifi_on", package="android")

    write_settings_xml(tree, output_path)
    return output_path


# ---------------------------------------------------------------------------
# settings_secure.xml 修改
# ---------------------------------------------------------------------------

def modify_settings_secure(
    input_path: Path,
    output_path: Path,
    *,
    android_id: str | None = None,
) -> Path:
    """修改 settings_secure.xml。

    从日志中提取的修改点：
    - android_id: 随机生成新值
    - lockscreen.disabled: 0 → 1

    Args:
        input_path: 原始 XML 路径
        output_path: 修改后的输出路径
        android_id: 新 android_id（None 则自动生成）

    Returns:
        输出文件路径
    """
    if android_id is None:
        android_id = generate_android_id()

    tree = read_settings_xml(input_path)
    root = tree.getroot()

    # 修改 android_id
    modify_setting(
        root, "android_id",
        value=android_id,
        default_value=android_id,
    )

    # lockscreen.disabled: 0 → 1
    modify_setting(
        root, "lockscreen.disabled",
        value="1",
        default_value="1",
    )

    write_settings_xml(tree, output_path)
    return output_path
