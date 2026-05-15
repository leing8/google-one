"""
设备随机化值生成器。

每次执行设备随机化时，部分值需要动态生成以避免指纹重复。
本模块提供所有可随机化字段的生成函数。

根据 7.0 vs 7.0.1 序列对齐分析，以下字段需要随机化：
- timezone:    从预设时区池中随机选择
- guid:        UUID v4 随机生成
- serial_no:   10 位大写字母+数字随机序列号

待定字段（暂用固定值）：
- mi_info_data: MiChangerPro AES 加密数据，无法逆向

不需要随机化的字段：
- config_hash:  工具版本签名，两次执行相同

参考：
- https://docs.python.org/3/library/uuid.html
- https://docs.python.org/3/library/secrets.html
"""

from __future__ import annotations

import secrets
import string
import uuid

# ---------------------------------------------------------------------------
# 时区池
# ---------------------------------------------------------------------------
# 来自 MiChangerPro 常用时区列表（基于 pcapng 两次执行样本）
_TIMEZONE_POOL: tuple[str, ...] = (
    # ── 美国时区（完整） ──────────────────────────────────
    # 东部
    "America/New_York",          # UTC-5  Eastern
    "America/Detroit",           # UTC-5  Eastern (Michigan)
    "America/Kentucky/Louisville",  # UTC-5  Eastern (Kentucky)
    "America/Kentucky/Monticello",  # UTC-5  Eastern (Kentucky)
    "America/Indiana/Indianapolis",  # UTC-5  Eastern (Indiana)
    "America/Indiana/Vincennes",    # UTC-5  Eastern (Indiana)
    "America/Indiana/Winamac",      # UTC-5  Eastern (Indiana)
    "America/Indiana/Marengo",      # UTC-5  Eastern (Indiana)
    "America/Indiana/Petersburg",   # UTC-5  Eastern (Indiana)
    "America/Indiana/Vevay",        # UTC-5  Eastern (Indiana)
    # 中部
    "America/Chicago",           # UTC-6  Central
    "America/Indiana/Tell_City",    # UTC-6  Central (Indiana)
    "America/Indiana/Knox",         # UTC-6  Central (Indiana)
    "America/Menominee",         # UTC-6  Central (Michigan)
    "America/North_Dakota/Center",     # UTC-6  Central (North Dakota)
    "America/North_Dakota/New_Salem",  # UTC-6  Central (North Dakota)
    "America/North_Dakota/Beulah",     # UTC-6  Central (North Dakota)
    # 山地
    "America/Denver",            # UTC-7  Mountain
    "America/Boise",             # UTC-7  Mountain (Idaho)
    "America/Phoenix",           # UTC-7  Mountain (Arizona, 无夏令时)
    # 太平洋
    "America/Los_Angeles",       # UTC-8  Pacific
    # 阿拉斯加
    "America/Anchorage",         # UTC-9  Alaska
    "America/Juneau",            # UTC-9  Alaska
    "America/Sitka",             # UTC-9  Alaska
    "America/Metlakatla",        # UTC-9  Alaska
    "America/Yakutat",           # UTC-9  Alaska
    "America/Nome",              # UTC-9  Alaska
    # 夏威夷 / 阿留申
    "America/Adak",              # UTC-10 Hawaii-Aleutian (有夏令时)
    "Pacific/Honolulu",          # UTC-10 Hawaii (无夏令时)
    # ── 其他地区 ──────────────────────────────────────────
    "America/Sao_Paulo",         # UTC-3
    "Europe/London",             # UTC+0
    "Europe/Paris",              # UTC+1
    "Europe/Berlin",             # UTC+1
    "Europe/Moscow",             # UTC+3
    "Asia/Dubai",                # UTC+4
    "Asia/Kolkata",              # UTC+5:30
    "Asia/Bangkok",              # UTC+7
    "Asia/Shanghai",             # UTC+8
    "Asia/Tokyo",                # UTC+9
    "Australia/Sydney",          # UTC+10
    "Pacific/Auckland",          # UTC+12
)

# 序列号字符集（大写字母 + 数字）
_SERIAL_CHARSET: str = string.ascii_uppercase + string.digits

# 序列号长度（来自 pcapng: 26JIK8TVGH, 61GGRAORRG — 均为 10 位）
_SERIAL_LENGTH: int = 10


def random_timezone() -> str:
    """从预设时区池中随机选择一个时区。

    Returns:
        IANA 时区字符串（如 "America/Phoenix"）
    """
    return secrets.choice(_TIMEZONE_POOL)


def random_guid() -> str:
    """生成 UUID v4 格式的唯一标识。

    Returns:
        标准 UUID v4 字符串（如 "0377a81e-4567-4eef-978b-0c4fe12406d7"）
    """
    return str(uuid.uuid4())


def random_serial_no(length: int = _SERIAL_LENGTH) -> str:
    """生成随机设备序列号。

    Args:
        length: 序列号长度，默认 10 位

    Returns:
        大写字母+数字组成的随机字符串（如 "61GGRAORRG"）
    """
    return "".join(secrets.choice(_SERIAL_CHARSET) for _ in range(length))
