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
    - michanger.import_file_to_phone:   文件导入到手机（严格还原 13.0-Import File to Phone.pcapng）
    - michanger.random_change_sim_info: SIM 信息随机化（严格还原 14.0-Random & Change SIM Info Only.pcapng）
    - michanger.change_location_only:   位置信息变更（严格还原 15.0-Change Location Only.pcapng）
    - michanger.config_proxy:           设备代理配置（严格还原 16.0-Config Proxy.pcapng）
    - michanger.clean_all_proxy:        清除全局代理（严格还原 17.0-Clean All Proxy.pcapng）
    - michanger.clear_play_store:       清除 Play Store 数据（严格还原 18.0-Clear Google Play Store.pcapng）
"""

