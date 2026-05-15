"""
Install Magisk & Root Phone — Android 设备 Magisk 安装模块。

严格按照 5.0-Install Magisk && Root Phone.pcapng 抓包还原的命令序列，
通过 TWRP Recovery 安装 Magisk，实现设备 Root。

命令序列（6 步）：
    1. adb reboot recovery                → 进入 TWRP
    2. adb shell twrp --version           → 验证 TWRP
    3. adb push Magisk.zip /sdcard/       → 推送安装包
    4. adb shell twrp install /sdcard/Magisk.zip → 安装
    5. adb shell rm -rf /sdcard/Magisk.zip → 清理
    6. adb reboot                         → 重启

公共 API：
    - install_magisk(): 执行完整 Magisk 安装流程
    - MagiskInstallResult: 安装结果数据类
    - TwrpInfo: TWRP 版本信息数据类
"""

from .install_magisk import install_magisk
from .models import MagiskInstallResult, TwrpInfo

__all__ = [
    "MagiskInstallResult",
    "TwrpInfo",
    "install_magisk",
]
