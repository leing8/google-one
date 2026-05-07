"""
Build Prop Modifier — build.prop 修改工具与常量定义。

提供 TWRP Recovery 模式下通过 ``sed`` 命令修改 build.prop 文件的
工具函数，以及从 Wireshark 抓包 ``7.0-Randomly change device.txt``
中提取的安全属性和清理路径常量。

抓包中涉及的 build.prop 文件::

    - /prop.default                           — TWRP 默认属性
    - /system_root/system/build.prop          — 系统 build.prop
    - /system_root/system/product/build.prop  — product 分区
    - /system_ext/build.prop                  — system_ext 分区
    - /odm/etc/build.prop                     — ODM 分区
    - /vendor/build.prop                      — vendor 分区

工具函数::

    generate_sed_command()            — 生成 sed -i 's|old|new|g' 命令
    generate_delete_command()         — 生成 sed -i '/^pattern/d' 命令
    generate_grep_or_append_command() — 生成 grep && sed || echo 命令

模块用法::

    from build_prop_modifier import SECURITY_PROPS, generate_grep_or_append_command

    for key, value in SECURITY_PROPS:
        cmd = generate_grep_or_append_command(key, value, "/system/build.prop")
        adb.shell(cmd)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SedReplacement:
    """单条 sed 替换指令。

    Attributes:
        old: 原始字符串（sed 的搜索模式）。
        new: 替换后的字符串。
    """

    old: str
    new: str


@dataclass(frozen=True, slots=True)
class BuildPropFile:
    """一个 build.prop 文件的修改描述。

    Attributes:
        path: 设备端 build.prop 文件绝对路径。
        replacements: 需要执行的 sed 替换列表。
        delete_patterns: 需要删除的行匹配模式列表（``sed '/^pattern/d'``）。
    """

    path: str
    replacements: tuple[SedReplacement, ...]
    delete_patterns: tuple[str, ...]


def generate_sed_command(
    replacement: SedReplacement,
    filepath: str,
) -> str:
    """生成单条 ``sed -i 's|old|new|g'`` 命令。

    使用 ``|`` 作为 sed 分隔符，避免路径中的 ``/`` 冲突。

    参数：
        replacement: 替换指令。
        filepath: 设备端目标文件路径。

    返回：
        完整的 sed 命令字符串。
    """
    return f"sed -i 's|{replacement.old}|{replacement.new}|g' {filepath}"


def generate_delete_command(pattern: str, filepath: str) -> str:
    """生成 ``sed -i '/^pattern/d'`` 行删除命令。

    对应抓包中删除 ``#Removed_By_MiChangerPro`` 等标记行的操作。

    参数：
        pattern: 行首匹配模式。
        filepath: 设备端目标文件路径。

    返回：
        完整的 sed 删除命令字符串。
    """
    return f"sed -i '/^{pattern}/d' {filepath}"


def generate_grep_or_append_command(
    key: str,
    value: str,
    filepath: str,
) -> str:
    """生成 ``grep -q && sed || echo`` 幂等属性设置命令。

    对应抓包中安全属性的写入逻辑：
    - 如果属性已存在 → ``sed`` 原地替换
    - 如果属性不存在 → ``echo`` 追加到文件末尾

    参数：
        key: 属性键名, e.g. ``"ro.secure"``。
        value: 属性值, e.g. ``"1"``。
        filepath: 设备端目标文件路径。

    返回：
        完整的 shell 命令字符串。
    """
    return (
        f"grep -q '^{key}=' {filepath} && "
        f"sed -i 's/^{key}=.*/{key}={value}/' {filepath} "
        f"|| echo '{key}={value}' >> {filepath}"
    )


# ---------------------------------------------------------------------------
# 安全属性
# ---------------------------------------------------------------------------

#: 需要写入 ``/system/build.prop`` 的安全属性列表
#: 对应抓包中 ``grep -q ... && sed ... || echo ...`` 命令序列
#: 这些属性使设备看起来处于正常的 locked bootloader 状态
SECURITY_PROPS: tuple[tuple[str, str], ...] = (
    ("ro.secure", "1"),
    ("ro.debuggable", "0"),
    ("ro.crypto.state", "encrypted"),
    ("init.svc.flash_recovery", "stop"),
    ("ro.boot.verifiedbootstate", "green"),
    ("ro.boot.flash.locked", "1"),
    ("sys.oem_unlock_allowed", "0"),
    ("ro.secureboot.lockstate", "locked"),
)


# ---------------------------------------------------------------------------
# MiChangerPro 信息清理路径
# ---------------------------------------------------------------------------

#: 旧 mi_info 目录的所有可能位置（对应抓包中的 ``rm -rf`` 清理序列）
#: 清理后会在 ``/system_root/system/etc/mi`` 下重建新文件
MI_INFO_CLEANUP_PATHS: tuple[str, ...] = (
    "/data/mi_info",
    "/system/system/etc/mi_info",
    "/system/etc/mi_info",
    "/system_root/system/etc/mi_info",
    "/system/system/etc/mi",
    "/system/etc/mi",
    "/system_root/system/etc/mi",
)


# ---------------------------------------------------------------------------
# Recovery 痕迹清理路径
# ---------------------------------------------------------------------------

#: 需要删除的 Recovery/OTA 相关文件（对应抓包中阶段 8 的 ``rm -rf`` 命令）
#: 这些文件会暴露设备曾使用过 TWRP Recovery
RECOVERY_CLEANUP_PATHS: tuple[str, ...] = (
    "/system/addon.d",
    "/system/bin/install-recovery.sh",
    "/vendor/bin/install-recovery.sh",
    "/sdcard/TWRP",
)
