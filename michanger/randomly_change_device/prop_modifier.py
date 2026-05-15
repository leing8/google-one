"""
build.prop 属性修改引擎。

对应 pcapng 第 6-8 阶段：读取设备各分区 build.prop，
通过 sed -i 's|old|new|g' 替换属性值为目标设备配置。

覆盖的属性文件（按抓包顺序）：
    1. /prop.default                           （pcapng 命令 51-139）
    2. /system_root/system/product/build.prop   （pcapng 命令 140-156）
    3. /system_root/system/build.prop           （pcapng 命令 157-186）
    4. /system_ext/build.prop                   （pcapng 命令 188-204）
    5. /odm/etc/build.prop                      （pcapng 命令 205-219）
    6. /vendor/build.prop                       （pcapng 命令 220-240）

每个文件的替换键列表严格来自 pcapng 的 sed 命令。

参考：
- https://docs.python.org/3/library/re.html
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from michanger.common import AdbExecutor
from michanger.common import DeviceProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PropReplacement:
    """单条属性替换。"""

    key: str
    old_value: str
    new_value: str


# ------------------------------------------------------------------
# build.prop 解析
# ------------------------------------------------------------------

_PROP_LINE_RE: re.Pattern[str] = re.compile(
    r"^([a-zA-Z0-9_.]+)\s*=\s*(.*)$"
)


def parse_build_prop(content: str) -> dict[str, str]:
    """解析 build.prop 文件内容为 key=value 字典。"""
    props: dict[str, str] = {}
    for line in content.splitlines():
        m = _PROP_LINE_RE.match(line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def read_prop_file(adb: AdbExecutor, path: str) -> str:
    """从设备读取属性文件内容。"""
    result = adb.shell(f"cat {path}", timeout=15.0)
    logger.debug("读取 %s: %d 字节", path, len(result.output))
    return result.output


# ------------------------------------------------------------------
# sed 命令生成与执行
# ------------------------------------------------------------------

def _run_sed(adb: AdbExecutor, path: str, old: str, new: str) -> None:
    """执行单条 sed 替换（使用 | 分隔符，与抓包一致）。"""
    adb.shell(f"sed -i 's|{old}|{new}|g' {path}")
    logger.debug("sed: %s → %s in %s", old[:60], new[:60], path)


def _cleanup_markers(adb: AdbExecutor, path: str) -> None:
    """删除 #Removed_By_MiChangerPro 标记行。"""
    adb.shell(f"sed -i '/^#Removed_By_MiChangerPro/d' {path}")


def _remove_line(adb: AdbExecutor, path: str, pattern: str) -> None:
    """删除匹配的整行。"""
    adb.shell(f"sed -i '/^{pattern}/d' {path}")


def _grep_or_append(
    adb: AdbExecutor, path: str, key: str, value: str,
) -> None:
    """若 key 存在则替换，否则追加（pcapng grep -q + sed || echo 模式）。"""
    cmd = (
        f"grep -q '^{key}=' {path} "
        f"&& sed -i 's/^{key}=.*/{key}={value}/' {path} "
        f"|| echo '{key}={value}' >> {path}"
    )
    adb.shell(cmd)


# ------------------------------------------------------------------
# 属性键→目标值 映射
#
# 每个 tuple: (property_key, resolver)
# resolver 接收 DeviceProfile 返回目标值字符串
# 严格按照 pcapng 中每个 sed 命令的目标值定义
# ------------------------------------------------------------------

# 类型别名：属性值解析器
Resolver = Callable[[DeviceProfile], str]

# 简写 helper
_brand: Resolver = lambda p: p.brand
_brand_lc: Resolver = lambda p: p.brand.lower()  # "google" 小写
_model: Resolver = lambda p: p.model
_mfr: Resolver = lambda p: p.manufacturer
_dev: Resolver = lambda p: p.device
_prod: Resolver = lambda p: p.product
_board: Resolver = lambda p: p.board
_fp: Resolver = lambda p: p.fingerprint
_bid: Resolver = lambda p: p.build_id
_tags: Resolver = lambda p: p.build_tags
_type: Resolver = lambda p: p.build_type
_inc: Resolver = lambda p: p.incremental
_date: Resolver = lambda p: p.build_date
_dutc: Resolver = lambda p: p.build_date_utc
_ver: Resolver = lambda p: p.android_version
_user: Resolver = lambda p: p.build_user
_host: Resolver = lambda p: p.build_host
_flavor: Resolver = lambda p: f"{p.product}-{p.build_type}"
_desc: Resolver = lambda p: (
    f"{p.product}-{p.build_type} {p.android_version} "
    f"{p.build_id} {p.incremental} {p.build_tags}"
)

# 指纹中的 / 在 sed 中需要转义（pcapng 使用 \/ 格式）
# 但由于我们使用 | 作为分隔符，不需要转义 /
# pcapng 中的转义是因为原始工具使用了 / 分隔符

# ------------------------------------------------------------------
# /prop.default 属性键列表（pcapng 命令 52-137）
# ------------------------------------------------------------------

_PROP_DEFAULT_KEYS: tuple[tuple[str, Resolver], ...] = (
    # bootimage（命令 53-57）
    ("ro.bootimage.build.date", _date),
    ("ro.build.date", _date),
    ("ro.bootimage.build.date.utc", _dutc),
    ("ro.build.date.utc", _dutc),
    ("ro.bootimage.build.fingerprint", _fp),
    # build id/display（命令 58-59）
    ("ro.build.id", _bid),
    ("ro.build.display.id", _bid),
    # build meta（命令 60-67）
    ("ro.build.tags", _tags),
    ("ro.build.type", _type),
    ("ro.build.version.incremental", _inc),
    ("ro.build.user", _user),
    ("ro.build.host", _host),
    ("ro.build.flavor", _flavor),
    ("ro.build.product", _dev),
    ("ro.build.description", _desc),
    # ODM（命令 68-79）
    ("ro.product.odm.brand", _brand),
    ("ro.product.odm.model", _model),
    ("ro.product.odm.manufacturer", _mfr),
    ("ro.product.odm.device", _dev),
    ("ro.odm.build.date", _date),
    ("ro.odm.build.date.utc", _dutc),
    ("ro.odm.build.fingerprint", _fp),
    ("ro.odm.build.id", _bid),
    ("ro.odm.build.tags", _tags),
    ("ro.odm.build.type", _type),
    ("ro.odm.build.version.incremental", _inc),
    ("ro.product.odm.name", _prod),
    # System（命令 80-91）
    ("ro.product.system.brand", _brand),
    ("ro.product.system.model", _model),
    ("ro.product.system.manufacturer", _mfr),
    ("ro.product.system.device", _dev),
    ("ro.system.build.date", _date),
    ("ro.system.build.date.utc", _dutc),
    ("ro.system.build.fingerprint", _fp),
    ("ro.system.build.id", _bid),
    ("ro.system.build.tags", _tags),
    ("ro.system.build.type", _type),
    ("ro.system.build.version.incremental", _inc),
    ("ro.product.system.name", _prod),
    # Vendor（命令 92-104）
    ("ro.product.vendor.brand", _brand),
    ("ro.product.vendor.model", _model),
    ("ro.product.vendor.manufacturer", _mfr),
    ("ro.product.vendor.device", _dev),
    ("ro.vendor.build.date", _date),
    ("ro.vendor.build.date.utc", _dutc),
    ("ro.vendor.build.fingerprint", _fp),
    ("ro.vendor.build.id", _bid),
    ("ro.vendor.build.tags", _tags),
    ("ro.vendor.build.type", _type),
    ("ro.vendor.build.version.incremental", _inc),
    ("ro.product.vendor.name", _prod),
    ("ro.product.board", _board),
    # System_ext（命令 105-116）
    ("ro.system_ext.build.date", _date),
    ("ro.system_ext.build.date.utc", _dutc),
    ("ro.system_ext.build.fingerprint", _fp),
    ("ro.system_ext.build.id", _bid),
    ("ro.system_ext.build.tags", _tags),
    ("ro.system_ext.build.type", _type),
    ("ro.system_ext.build.version.incremental", _inc),
    ("ro.product.system_ext.brand", _brand_lc),  # 注意: 小写 "google"
    ("ro.product.system_ext.device", _dev),
    ("ro.product.system_ext.manufacturer", _mfr),
    ("ro.product.system_ext.model", _model),
    ("ro.product.system_ext.name", _prod),
    # Product（命令 117-131）
    ("ro.product.product.brand", _brand),
    ("ro.product.product.model", _model),
    ("ro.product.product.manufacturer", _mfr),
    ("ro.product.product.name", _prod),
    ("ro.product.product.device", _dev),
    ("ro.product.build.date", _date),
    ("ro.product.build.date.utc", _dutc),
    ("ro.product.build.fingerprint", _fp),
    ("ro.product.build.id", _bid),
    ("ro.product.build.tags", _tags),
    ("ro.product.build.type", _type),
    ("ro.product.build.version.incremental", _inc),
    ("ro.build.version.release_or_codename", _ver),
    ("ro.product.build.version.release", _ver),
    ("ro.product.build.version.release_or_codename", _ver),
    # Version release（命令 132-135）
    ("ro.system.build.version.release", _ver),
    ("ro.system.build.version.release_or_codename", _ver),
    ("ro.system_ext.build.version.release", _ver),
    ("ro.system_ext.build.version.release_or_codename", _ver),
)

# ------------------------------------------------------------------
# /system_root/system/product/build.prop 属性键（pcapng 命令 141-154）
# ------------------------------------------------------------------

_PRODUCT_BUILD_PROP_KEYS: tuple[tuple[str, Resolver], ...] = (
    ("ro.product.product.brand", _brand),
    ("ro.product.product.model", _model),
    ("ro.product.product.manufacturer", _mfr),
    ("ro.product.product.name", _prod),
    ("ro.product.product.device", _dev),
    ("ro.product.build.date", _date),
    ("ro.product.build.date.utc", _dutc),
    ("ro.product.build.fingerprint", _fp),
    ("ro.product.build.id", _bid),
    ("ro.product.build.tags", _tags),
    ("ro.product.build.type", _type),
    ("ro.product.build.version.incremental", _inc),
    ("ro.product.build.version.release", _ver),
    ("ro.product.build.version.release_or_codename", _ver),
)

# ------------------------------------------------------------------
# /system_root/system/build.prop 属性键（pcapng 命令 158-185）
# ------------------------------------------------------------------

_SYSTEM_BUILD_PROP_KEYS: tuple[tuple[str, Resolver], ...] = (
    ("ro.build.date", _date),
    ("ro.build.date.utc", _dutc),
    ("ro.build.fingerprint", _fp),
    ("ro.build.id", _bid),
    ("ro.build.display.id", _bid),
    ("ro.build.tags", _tags),
    ("ro.build.type", _type),
    ("ro.build.version.incremental", _inc),
    ("ro.build.user", _user),
    ("ro.build.host", _host),
    ("ro.build.flavor", _flavor),
    ("ro.build.product", _dev),
    ("ro.build.description", _desc),
    ("ro.product.system.brand", _brand),
    ("ro.product.system.model", _model),
    ("ro.product.system.manufacturer", _mfr),
    ("ro.product.system.device", _dev),
    ("ro.system.build.date", _date),
    ("ro.system.build.date.utc", _dutc),
    ("ro.system.build.fingerprint", _fp),
    ("ro.system.build.id", _bid),
    ("ro.system.build.tags", _tags),
    ("ro.system.build.type", _type),
    ("ro.system.build.version.incremental", _inc),
    ("ro.product.system.name", _prod),
    ("ro.build.version.release_or_codename", _ver),
    ("ro.system.build.version.release", _ver),
    ("ro.system.build.version.release_or_codename", _ver),
)

# ------------------------------------------------------------------
# /system_ext/build.prop 属性键（pcapng 命令 189-202）
# ------------------------------------------------------------------

_SYSTEM_EXT_BUILD_PROP_KEYS: tuple[tuple[str, Resolver], ...] = (
    ("ro.system_ext.build.date", _date),
    ("ro.system_ext.build.date.utc", _dutc),
    ("ro.system_ext.build.fingerprint", _fp),
    ("ro.system_ext.build.id", _bid),
    ("ro.system_ext.build.tags", _tags),
    ("ro.system_ext.build.type", _type),
    ("ro.system_ext.build.version.incremental", _inc),
    ("ro.product.system_ext.brand", _brand_lc),
    ("ro.product.system_ext.device", _dev),
    ("ro.product.system_ext.manufacturer", _mfr),
    ("ro.product.system_ext.model", _model),
    ("ro.product.system_ext.name", _prod),
    ("ro.system_ext.build.version.release", _ver),
    ("ro.system_ext.build.version.release_or_codename", _ver),
)

# ------------------------------------------------------------------
# /odm/etc/build.prop 属性键（pcapng 命令 206-217）
# ------------------------------------------------------------------

_ODM_BUILD_PROP_KEYS: tuple[tuple[str, Resolver], ...] = (
    ("ro.product.odm.brand", _brand),
    ("ro.product.odm.model", _model),
    ("ro.product.odm.manufacturer", _mfr),
    ("ro.product.odm.device", _dev),
    ("ro.odm.build.date", _date),
    ("ro.odm.build.date.utc", _dutc),
    ("ro.odm.build.fingerprint", _fp),
    ("ro.odm.build.id", _bid),
    ("ro.odm.build.tags", _tags),
    ("ro.odm.build.type", _type),
    ("ro.odm.build.version.incremental", _inc),
    ("ro.product.odm.name", _prod),
)

# ------------------------------------------------------------------
# /vendor/build.prop 属性键（pcapng 命令 221-236）
# ------------------------------------------------------------------

_VENDOR_BUILD_PROP_KEYS: tuple[tuple[str, Resolver], ...] = (
    ("ro.bootimage.build.date", _date),
    ("ro.bootimage.build.date.utc", _dutc),
    ("ro.bootimage.build.fingerprint", _fp),
    ("ro.product.vendor.brand", _brand),
    ("ro.product.vendor.model", _model),
    ("ro.product.vendor.manufacturer", _mfr),
    ("ro.product.vendor.device", _dev),
    ("ro.vendor.build.date", _date),
    ("ro.vendor.build.date.utc", _dutc),
    ("ro.vendor.build.fingerprint", _fp),
    ("ro.vendor.build.id", _bid),
    ("ro.vendor.build.tags", _tags),
    ("ro.vendor.build.type", _type),
    ("ro.vendor.build.version.incremental", _inc),
    ("ro.product.vendor.name", _prod),
    ("ro.product.board", _board),
)


# ------------------------------------------------------------------
# 通用替换执行引擎
# ------------------------------------------------------------------

def _apply_key_replacements(
    adb: AdbExecutor,
    path: str,
    keys: tuple[tuple[str, Resolver], ...],
    current_props: dict[str, str],
    profile: DeviceProfile,
) -> int:
    """对指定属性文件执行键列表中的所有 sed 替换。

    对于每个键：
    1. 从 current_props 查找当前值（old_value）
    2. 用 resolver 计算目标值（new_value）
    3. 如果 old != new，执行 sed 替换

    Args:
        adb: ADB 执行器
        path: 设备端属性文件路径
        keys: (属性键, 值解析器) 元组列表
        current_props: 当前属性字典
        profile: 目标设备配置

    Returns:
        执行的 sed 命令数量
    """
    count = 0
    for key, resolver in keys:
        old_val = current_props.get(key)
        if old_val is None:
            logger.debug("键不存在于设备，跳过: %s", key)
            continue

        new_val = resolver(profile)
        if old_val == new_val:
            logger.debug("值相同，仍执行 sed: %s=%s", key, new_val[:50])

        # 严格按抓包执行：即使值相同也执行 sed（抓包中有此情况）
        _run_sed(adb, path, f"{key}={old_val}", f"{key}={new_val}")
        count += 1

    return count


# ------------------------------------------------------------------
# 公共 API — 按抓包顺序修改各分区
# ------------------------------------------------------------------

def modify_prop_default(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /prop.default（pcapng 命令 51-139）。

    Returns:
        执行的命令数量
    """
    path = "/prop.default"
    count = 0

    # Step 1: 读取当前属性（命令 51）
    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    # Step 2: 硬编码 ro.debuggable（命令 52）
    _run_sed(adb, path, "ro.debuggable=1", "ro.debuggable=0")
    count += 1

    # Step 3: 按键列表执行替换（命令 53-135）
    count += _apply_key_replacements(
        adb, path, _PROP_DEFAULT_KEYS, current, profile,
    )

    # Step 4: 读取验证（命令 136）
    read_prop_file(adb, path)
    count += 1

    # Step 5: 清理标记（命令 137）
    _cleanup_markers(adb, path)
    count += 1

    # Step 6: 删除 ro.hardware.keystore_desede（命令 138-139，执行两次）
    _remove_line(adb, path, "ro.hardware.keystore_desede")
    count += 1
    _remove_line(adb, path, "ro.hardware.keystore_desede")
    count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def modify_product_build_prop(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /system_root/system/product/build.prop（pcapng 命令 140-156）。"""
    path = "/system_root/system/product/build.prop"
    count = 0

    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    count += _apply_key_replacements(
        adb, path, _PRODUCT_BUILD_PROP_KEYS, current, profile,
    )

    read_prop_file(adb, path)
    count += 1
    _cleanup_markers(adb, path)
    count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def modify_system_build_prop(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /system_root/system/build.prop（pcapng 命令 157-186）。"""
    path = "/system_root/system/build.prop"
    count = 0

    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    count += _apply_key_replacements(
        adb, path, _SYSTEM_BUILD_PROP_KEYS, current, profile,
    )

    read_prop_file(adb, path)
    count += 1
    _cleanup_markers(adb, path)
    count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def modify_system_ext_build_prop(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /system_ext/build.prop（pcapng 命令 188-204）。"""
    path = "/system_ext/build.prop"
    count = 0

    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    count += _apply_key_replacements(
        adb, path, _SYSTEM_EXT_BUILD_PROP_KEYS, current, profile,
    )

    read_prop_file(adb, path)
    count += 1
    _cleanup_markers(adb, path)
    count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def modify_odm_build_prop(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /odm/etc/build.prop（pcapng 命令 205-219）。"""
    path = "/odm/etc/build.prop"
    count = 0

    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    count += _apply_key_replacements(
        adb, path, _ODM_BUILD_PROP_KEYS, current, profile,
    )

    read_prop_file(adb, path)
    count += 1
    _cleanup_markers(adb, path)
    count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def modify_vendor_build_prop(
    adb: AdbExecutor,
    profile: DeviceProfile,
) -> int:
    """修改 /vendor/build.prop（pcapng 命令 220-240）。"""
    path = "/vendor/build.prop"
    count = 0

    content = read_prop_file(adb, path)
    current = parse_build_prop(content)
    count += 1

    count += _apply_key_replacements(
        adb, path, _VENDOR_BUILD_PROP_KEYS, current, profile,
    )

    read_prop_file(adb, path)
    count += 1
    _cleanup_markers(adb, path)
    count += 1

    # 条件清理（pcapng 命令 239-240）
    # 仅当行存在时执行（第二次执行时这些行已被删除）
    if "ro.hardware.keystore_desede" in content:
        _remove_line(adb, path, "ro.hardware.keystore_desede")
        count += 1
    if "ro.hardware.egl" in content:
        _remove_line(adb, path, "ro.hardware.egl")
        count += 1

    logger.info("修改 %s 完成: %d 条命令", path, count)
    return count


def set_security_props(adb: AdbExecutor) -> int:
    """设置安全属性（pcapng 命令 241-248）。

    使用 grep -q + sed || echo 模式确保属性存在并设为正确值。

    Returns:
        执行的命令数量
    """
    path = "/system/build.prop"
    count = 0

    security_props: tuple[tuple[str, str], ...] = (
        ("ro.secure", "1"),
        ("ro.debuggable", "0"),
        ("ro.crypto.state", "encrypted"),
        ("init.svc.flash_recovery", "stop"),
        ("ro.boot.verifiedbootstate", "green"),
        ("ro.boot.flash.locked", "1"),
        ("sys.oem_unlock_allowed", "0"),
        ("ro.secureboot.lockstate", "locked"),
    )

    for key, value in security_props:
        _grep_or_append(adb, path, key, value)
        count += 1

    logger.info("安全属性设置完成: %d 条", count)
    return count
