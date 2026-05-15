"""
Randomly Change Device — 设备信息随机化模块。

严格按照 7.0-Randomly change device.pcapng 抓包还原的命令序列，
修改设备的全部系统属性（build.prop、mi_info、settings 等），
使其看起来是一台全新的设备。

命令序列（11 阶段 / 333 条命令）：
    1.  设备信息探测（locale、Gmail 账号）
    2.  系统设置初始化（HOME、WiFi、开发者选项、时区、锁屏）
    3.  pm clear 清理 23 个应用数据
    4.  重启进入 TWRP Recovery
    5.  TWRP 挂载 7 个分区 + remount rw
    6.  修改 /prop.default（88 条 sed）
    7.  修改 5 个分区的 build.prop
    8.  安全属性 + mi_info + config 写入
    9.  深度清理应用数据 + 系统数据
    10. pull/modify/push 3 个 XML 文件 + restorecon
    11. 重启 → 等待启动 → 验证设备属性

公共 API：
    - randomly_change_device(): 执行完整设备随机化流程
    - ChangeDeviceResult: 执行结果数据类

    DeviceProfile 和 load_profile 已迁移至 michanger.common：
    - from michanger.common import DeviceProfile, load_profile
"""

from michanger.common import DeviceProfile, load_profile
from .models import ChangeDeviceResult
from .randomly_change_device import randomly_change_device

__all__ = [
    "ChangeDeviceResult",
    "DeviceProfile",
    "load_profile",
    "randomly_change_device",
]

