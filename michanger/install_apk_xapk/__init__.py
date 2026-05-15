"""
Install Apk-XApk -- APK/XAPK 批量安装模块。

安装 apk/ 目录中的所有 .apk 和 .xapk 文件，然后启用 Google Play Store。
严格按照 12.0-Install Apk-XApk.pcapng 抓包还原的命令序列实现。

pcapng 等效流程：
    对每个 .xapk 文件：
        1. 解析 manifest.json 获取分割 APK 列表
        2. 解压 APK 到临时目录
        3. adb install-multiple -r -d -t --user 0 <apk1> <apk2> ...
           （等价于 pcapng 中的 install-create -> install-write x N -> install-commit）
    对每个 .apk 文件：
        adb install -r -d -t --user 0 <file.apk>
    最后：
        adb shell pm enable com.android.vending

公共 API：
    - install_apk_xapk(): 执行完整安装流程
    - InstallApkXapkResult: 整体安装结果数据类
    - PackageInstallResult: 单个包安装结果数据类
    - ApkInfo: APK 文件信息数据类
    - XapkInfo: XAPK 包信息数据类
    - parse_xapk(): 解析 XAPK 文件
    - extract_xapk(): 解压 XAPK 文件
    - XapkParseError: XAPK 解析错误
"""

from .install_apk_xapk import install_apk_xapk
from .models import (
    ApkInfo,
    InstallApkXapkResult,
    PackageInstallResult,
    XapkInfo,
)
from .xapk_parser import XapkParseError, extract_xapk, parse_xapk

__all__ = [
    "ApkInfo",
    "InstallApkXapkResult",
    "PackageInstallResult",
    "XapkInfo",
    "XapkParseError",
    "extract_xapk",
    "install_apk_xapk",
    "parse_xapk",
]
