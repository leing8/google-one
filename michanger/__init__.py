"""
MiChanger — Android 设备自动化管理工具集。

子模块：
    - michanger.common:                 通用共享（ADB 执行器、数据模型、CLI 工具）
    - michanger.install_magisk:         通过 TWRP 安装 Magisk
    - michanger.install_modules:        批量安装 Magisk 模块
    - michanger.install_apk_xapk:       批量安装 APK/XAPK 分割包
    - michanger.load_device:            设备探测与信息收集
    - michanger.randomly_change_device: 设备信息随机化（build.prop/mi_info/settings）
    - michanger.reboot:                 设备重启（严格还原 9.0-Reboot.pcapng）
    - michanger.update_integrity_fix:   更新 Integrity Fix（Tricky Store + PIF Premium + 系统配置）
    - michanger.wipe_packages_reboot:   包清理与重启（严格还原 11.0-Wipe Packages & Reboot.pcapng）
"""

