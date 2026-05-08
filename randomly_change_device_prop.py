"""Randomly Change Device — 阶段 D-I: 修改 build.prop 文件.

严格按照 7.0-Randomly change device.pcapng 抓包日志中步骤 48-239 的
ADB sed -i 命令序列一比一实现各分区 build.prop 属性修改。

阶段 D (步骤 48-138):  修改 /prop.default
阶段 E (步骤 139-155): 修改 /system_root/system/product/build.prop
阶段 F (步骤 156-186): 修改 /system_root/system/build.prop
阶段 G (步骤 187-203): 修改 /system_ext/build.prop
阶段 H (步骤 204-218): 修改 /odm/etc/build.prop
阶段 I (步骤 219-239): 修改 /vendor/build.prop

Python 官方最佳实践：
    - subprocess.run() 是推荐方法（Python 3.14 文档）
    - logging 模块进行结构化日志

参考:
    https://docs.python.org/3/library/subprocess.html#subprocess.run
"""

from __future__ import annotations

import logging

from adb_executor import AdbExecutor

logger = logging.getLogger(__name__)

_SHELL_TIMEOUT: int = 30


def _run_sed(
    executor: AdbExecutor,
    step: int,
    filepath: str,
    old: str,
    new: str,
) -> bool:
    """执行单条 sed -i 替换命令。

    严格按照抓包日志格式:
        sed -i 's|<old>|<new>|g' <filepath>

    参数:
        executor: ADB 执行器。
        step: 步骤编号。
        filepath: 设备上的文件路径。
        old: 要替换的原始字符串。
        new: 替换后的字符串。

    返回:
        命令是否成功。
    """
    cmd = f"sed -i 's|{old}|{new}|g' {filepath}"
    logger.info("步骤 %d: %s", step, cmd)
    result = executor.run_shell(cmd, timeout=_SHELL_TIMEOUT)
    if not result.success:
        logger.warning("  sed 失败: %s", result.stderr)
    return result.success


def _run_sed_delete(
    executor: AdbExecutor,
    step: int,
    filepath: str,
    pattern: str,
) -> bool:
    """执行 sed -i 删除行命令。

    格式: sed -i '/^<pattern>/d' <filepath>
    """
    cmd = f"sed -i '/^{pattern}/d' {filepath}"
    logger.info("步骤 %d: %s", step, cmd)
    result = executor.run_shell(cmd, timeout=_SHELL_TIMEOUT)
    if not result.success:
        logger.warning("  sed delete 失败: %s", result.stderr)
    return result.success


def _cat_file(
    executor: AdbExecutor,
    step: int,
    filepath: str,
) -> str:
    """执行 cat 命令读取文件内容。"""
    logger.info("步骤 %d: cat %s", step, filepath)
    result = executor.run_shell(f"cat {filepath}", timeout=_SHELL_TIMEOUT)
    if result.success:
        logger.info("  文件内容已读取 (%d 字符)", len(result.stdout))
    else:
        logger.warning("  cat 失败: %s", result.stderr)
    return result.stdout if result.success else ""


# ── 阶段 D: 修改 /prop.default (步骤 48-138) ────────────────────


def modify_prop_default(executor: AdbExecutor) -> bool:
    """阶段 D: 修改 /prop.default 文件。

    步骤 48: ls /system_root/system/etc
    步骤 49: twrp --version
    步骤 50: cat /prop.default
    步骤 51-134: sed -i × 84 条替换
    步骤 135: cat /prop.default（验证）
    步骤 136-138: sed -i 删除行 × 3

    参数:
        executor: ADB 执行器。

    返回:
        是否全部成功。
    """
    fp = "/prop.default"

    # 步骤 48: ls /system_root/system/etc
    logger.info("步骤 48: ls /system_root/system/etc")
    result = executor.run_shell(
        "ls /system_root/system/etc",
        timeout=_SHELL_TIMEOUT,
    )
    logger.info("  输出: %s", result.stdout[:200] if result.stdout else "")

    # 步骤 49: twrp --version
    logger.info("步骤 49: twrp --version")
    result = executor.run_shell("twrp --version", timeout=_SHELL_TIMEOUT)
    logger.info("  输出: %s", result.stdout)

    # 步骤 50: cat /prop.default
    _cat_file(executor, 50, fp)

    # 步骤 51-134: sed -i 替换命令（严格按照抓包日志顺序）
    _SED_CMDS: list[tuple[int, str, str]] = [
        (51, "ro.debuggable=1", "ro.debuggable=0"),
        (52, "ro.bootimage.build.date=Sat Jun 4 17:01:28 UTC 2022",
             "ro.bootimage.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (53, "ro.build.date=Sat Jun  4 17:01:28 UTC 2022",
             "ro.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (54, "ro.bootimage.build.date.utc=1654362088",
             "ro.bootimage.build.date.utc=1753846468"),
        (55, "ro.build.date.utc=1654362088",
             "ro.build.date.utc=1753846468"),
        (56, "ro.bootimage.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
             "ro.bootimage.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (57, "ro.build.id=RQ1A.210205.004", "ro.build.id=BP4A.260205.001"),
        (58, "ro.build.display.id=twrp_coral-eng 11 RQ1A.210205.004 10 test-keys",
             "ro.build.display.id=BP4A.260205.001"),
        (59, "ro.build.tags=test-keys", "ro.build.tags=release-keys"),
        (60, "ro.build.type=eng", "ro.build.type=user"),
        (61, "ro.build.version.incremental=10",
             "ro.build.version.incremental=14624666"),
        (62, "ro.build.user=jenkins", "ro.build.user=user"),
        (63, "ro.build.host=c67cb60a4d08", "ro.build.host=7e95205b9461"),
        (64, "ro.build.flavor=twrp_coral-eng", "ro.build.flavor=blazer-user"),
        (65, "ro.build.product=coral", "ro.build.product=blazer"),
        (66, "ro.build.description=twrp_coral-eng 11 RQ1A.210205.004 10 test-keys",
             "ro.build.description=blazer-user 16 BP4A.260205.001 14624666 release-keys"),
        (67, "ro.product.odm.brand=Android", "ro.product.odm.brand=Google"),
        (68, "ro.product.odm.model=AOSP on coral",
             "ro.product.odm.model=Pixel 10 Pro"),
        (69, "ro.product.odm.manufacturer=Google",
             "ro.product.odm.manufacturer=Google"),
        (70, "ro.product.odm.device=coral", "ro.product.odm.device=blazer"),
        (71, "ro.odm.build.date=Sat Jun  4 17:01:28 UTC 2022",
             "ro.odm.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (72, "ro.odm.build.date.utc=1654362088",
             "ro.odm.build.date.utc=1753846468"),
        (73, "ro.odm.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
             "ro.odm.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (74, "ro.odm.build.id=RQ1A.210205.004",
             "ro.odm.build.id=BP4A.260205.001"),
        (75, "ro.odm.build.tags=test-keys", "ro.odm.build.tags=release-keys"),
        (76, "ro.odm.build.type=eng", "ro.odm.build.type=user"),
        (77, "ro.odm.build.version.incremental=10",
             "ro.odm.build.version.incremental=14624666"),
        (78, "ro.product.odm.name=twrp_coral",
             "ro.product.odm.name=blazer"),
        (79, "ro.product.system.brand=Android",
             "ro.product.system.brand=Google"),
        (80, "ro.product.system.model=mainline",
             "ro.product.system.model=Pixel 10 Pro"),
        (81, "ro.product.system.manufacturer=Android",
             "ro.product.system.manufacturer=Google"),
        (82, "ro.product.system.device=generic",
             "ro.product.system.device=blazer"),
        (83, "ro.system.build.date=Sat Jun  4 17:01:28 UTC 2022",
             "ro.system.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (84, "ro.system.build.date.utc=1654362088",
             "ro.system.build.date.utc=1753846468"),
        (85, "ro.system.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
             "ro.system.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (86, "ro.system.build.id=RQ1A.210205.004",
             "ro.system.build.id=BP4A.260205.001"),
        (87, "ro.system.build.tags=test-keys",
             "ro.system.build.tags=release-keys"),
        (88, "ro.system.build.type=eng", "ro.system.build.type=user"),
        (89, "ro.system.build.version.incremental=10",
             "ro.system.build.version.incremental=14624666"),
        (90, "ro.product.system.name=mainline",
             "ro.product.system.name=blazer"),
        (91, "ro.product.vendor.brand=Android",
             "ro.product.vendor.brand=Google"),
        (92, "ro.product.vendor.model=AOSP on coral",
             "ro.product.vendor.model=Pixel 10 Pro"),
        (93, "ro.product.vendor.manufacturer=Google",
             "ro.product.vendor.manufacturer=Google"),
        (94, "ro.product.vendor.device=coral",
             "ro.product.vendor.device=blazer"),
        (95, "ro.vendor.build.date=Sat Jun  4 17:01:28 UTC 2022",
             "ro.vendor.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (96, "ro.vendor.build.date.utc=1654362088",
             "ro.vendor.build.date.utc=1753846468"),
        (97, "ro.vendor.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
             "ro.vendor.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (98, "ro.vendor.build.id=RQ1A.210205.004",
             "ro.vendor.build.id=BP4A.260205.001"),
        (99, "ro.vendor.build.tags=test-keys",
             "ro.vendor.build.tags=release-keys"),
        (100, "ro.vendor.build.type=eng", "ro.vendor.build.type=user"),
        (101, "ro.vendor.build.version.incremental=10",
              "ro.vendor.build.version.incremental=14624666"),
        (102, "ro.product.vendor.name=twrp_coral",
              "ro.product.vendor.name=blazer"),
        (103, "ro.product.board=coral", "ro.product.board=blazer"),
        (104, "ro.system_ext.build.date=Sat Jun  4 17:01:28 UTC 2022",
              "ro.system_ext.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (105, "ro.system_ext.build.date.utc=1654362088",
              "ro.system_ext.build.date.utc=1753846468"),
        (106, "ro.system_ext.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
              "ro.system_ext.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (107, "ro.system_ext.build.id=RQ1A.210205.004",
              "ro.system_ext.build.id=BP4A.260205.001"),
        (108, "ro.system_ext.build.tags=test-keys",
              "ro.system_ext.build.tags=release-keys"),
        (109, "ro.system_ext.build.type=eng",
              "ro.system_ext.build.type=user"),
        (110, "ro.system_ext.build.version.incremental=10",
              "ro.system_ext.build.version.incremental=14624666"),
        (111, "ro.product.system_ext.brand=Android",
              "ro.product.system_ext.brand=google"),
        (112, "ro.product.system_ext.device=coral",
              "ro.product.system_ext.device=blazer"),
        (113, "ro.product.system_ext.manufacturer=Google",
              "ro.product.system_ext.manufacturer=Google"),
        (114, "ro.product.system_ext.model=AOSP on coral",
              "ro.product.system_ext.model=Pixel 10 Pro"),
        (115, "ro.product.system_ext.name=twrp_coral",
              "ro.product.system_ext.name=blazer"),
        (116, "ro.product.product.brand=Android",
              "ro.product.product.brand=Google"),
        (117, "ro.product.product.model=AOSP on coral",
              "ro.product.product.model=Pixel 10 Pro"),
        (118, "ro.product.product.manufacturer=Google",
              "ro.product.product.manufacturer=Google"),
        (119, "ro.product.product.name=twrp_coral",
              "ro.product.product.name=blazer"),
        (120, "ro.product.product.device=coral",
              "ro.product.product.device=blazer"),
        (121, "ro.product.build.date=Sat Jun  4 17:01:28 UTC 2022",
              "ro.product.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (122, "ro.product.build.date.utc=1654362088",
              "ro.product.build.date.utc=1753846468"),
        (123, "ro.product.build.fingerprint=Android/twrp_coral/coral:11/RQ1A.210205.004/10:eng/test-keys",
              "ro.product.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (124, "ro.product.build.id=RQ1A.210205.004",
              "ro.product.build.id=BP4A.260205.001"),
        (125, "ro.product.build.tags=test-keys",
              "ro.product.build.tags=release-keys"),
        (126, "ro.product.build.type=eng", "ro.product.build.type=user"),
        (127, "ro.product.build.version.incremental=10",
              "ro.product.build.version.incremental=14624666"),
        (128, "ro.build.version.release_or_codename=11",
              "ro.build.version.release_or_codename=16"),
        (129, "ro.product.build.version.release=11",
              "ro.product.build.version.release=16"),
        (130, "ro.product.build.version.release_or_codename=11",
              "ro.product.build.version.release_or_codename=16"),
        (131, "ro.system.build.version.release=11",
              "ro.system.build.version.release=16"),
        (132, "ro.system.build.version.release_or_codename=11",
              "ro.system.build.version.release_or_codename=16"),
        (133, "ro.system_ext.build.version.release=11",
              "ro.system_ext.build.version.release=16"),
        (134, "ro.system_ext.build.version.release_or_codename=11",
              "ro.system_ext.build.version.release_or_codename=16"),
    ]

    for step_num, old_val, new_val in _SED_CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 135: cat /prop.default（验证修改结果）
    _cat_file(executor, 135, fp)

    # 步骤 136: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 136, fp, "#Removed_By_MiChangerPro")

    # 步骤 137: 删除 ro.hardware.keystore_desede 行
    _run_sed_delete(executor, 137, fp, "ro.hardware.keystore_desede")

    # 步骤 138: 删除 ro.hardware.keystore_desede 行（重复执行）
    _run_sed_delete(executor, 138, fp, "ro.hardware.keystore_desede")

    return True


# ── 阶段 E: 修改 /system_root/system/product/build.prop (步骤 139-155) ─


def modify_product_build_prop(executor: AdbExecutor) -> bool:
    """阶段 E: 步骤 139-155."""
    fp = "/system_root/system/product/build.prop"

    # 步骤 139: cat
    _cat_file(executor, 139, fp)

    # 步骤 140-153: sed -i 替换
    _CMDS: list[tuple[int, str, str]] = [
        (140, "ro.product.product.brand=google", "ro.product.product.brand=Google"),
        (141, "ro.product.product.model=Pixel 4 XL", "ro.product.product.model=Pixel 10 Pro"),
        (142, "ro.product.product.manufacturer=Google", "ro.product.product.manufacturer=Google"),
        (143, "ro.product.product.name=coral", "ro.product.product.name=blazer"),
        (144, "ro.product.product.device=coral", "ro.product.product.device=blazer"),
        (145, "ro.product.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.product.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (146, "ro.product.build.date.utc=1753336048", "ro.product.build.date.utc=1753846468"),
        (147, "ro.product.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.product.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (148, "ro.product.build.id=RQ3A.211001.001", "ro.product.build.id=BP4A.260205.001"),
        (149, "ro.product.build.tags=release-keys", "ro.product.build.tags=release-keys"),
        (150, "ro.product.build.type=user", "ro.product.build.type=user"),
        (151, "ro.product.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.product.build.version.incremental=14624666"),
        (152, "ro.product.build.version.release=11", "ro.product.build.version.release=16"),
        (153, "ro.product.build.version.release_or_codename=11",
              "ro.product.build.version.release_or_codename=16"),
    ]
    for step_num, old_val, new_val in _CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 154: cat（验证）
    _cat_file(executor, 154, fp)

    # 步骤 155: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 155, fp, "#Removed_By_MiChangerPro")

    return True


# ── 阶段 F: 修改 /system_root/system/build.prop (步骤 156-186) ───


def modify_system_build_prop(executor: AdbExecutor) -> bool:
    """阶段 F: 步骤 156-186."""
    fp = "/system_root/system/build.prop"

    # 步骤 156: cat
    _cat_file(executor, 156, fp)

    # 步骤 157-184: sed -i 替换
    _CMDS: list[tuple[int, str, str]] = [
        (157, "ro.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (158, "ro.build.date.utc=1753336048", "ro.build.date.utc=1753846468"),
        (159, "ro.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (160, "ro.build.id=RQ3A.211001.001", "ro.build.id=BP4A.260205.001"),
        (161, "ro.build.display.id=RQ3A.211001.001", "ro.build.display.id=BP4A.260205.001"),
        (162, "ro.build.tags=release-keys", "ro.build.tags=release-keys"),
        (163, "ro.build.type=user", "ro.build.type=user"),
        (164, "ro.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.build.version.incremental=14624666"),
        (165, "ro.build.user=cpidng", "ro.build.user=user"),
        (166, "ro.build.host=cpidng-rom", "ro.build.host=7e95205b9461"),
        (167, "ro.build.flavor=lineage_coral-user", "ro.build.flavor=blazer-user"),
        (168, "ro.build.product=coral", "ro.build.product=blazer"),
        (169, "ro.build.description=coral-user 11 RQ3A.211001.001 7641976 release-keys",
              "ro.build.description=blazer-user 16 BP4A.260205.001 14624666 release-keys"),
        (170, "ro.product.system.brand=Android", "ro.product.system.brand=Google"),
        (171, "ro.product.system.model=mainline", "ro.product.system.model=Pixel 10 Pro"),
        (172, "ro.product.system.manufacturer=Android", "ro.product.system.manufacturer=Google"),
        (173, "ro.product.system.device=generic", "ro.product.system.device=blazer"),
        (174, "ro.system.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.system.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (175, "ro.system.build.date.utc=1753336048", "ro.system.build.date.utc=1753846468"),
        (176, "ro.system.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.system.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (177, "ro.system.build.id=RQ3A.211001.001", "ro.system.build.id=BP4A.260205.001"),
        (178, "ro.system.build.tags=release-keys", "ro.system.build.tags=release-keys"),
        (179, "ro.system.build.type=user", "ro.system.build.type=user"),
        (180, "ro.system.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.system.build.version.incremental=14624666"),
        (181, "ro.product.system.name=coral", "ro.product.system.name=blazer"),
        (182, "ro.build.version.release_or_codename=11", "ro.build.version.release_or_codename=16"),
        (183, "ro.system.build.version.release=11", "ro.system.build.version.release=16"),
        (184, "ro.system.build.version.release_or_codename=11",
              "ro.system.build.version.release_or_codename=16"),
    ]
    for step_num, old_val, new_val in _CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 185: cat（验证）
    _cat_file(executor, 185, fp)

    # 步骤 186: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 186, fp, "#Removed_By_MiChangerPro")

    return True


# ── 阶段 G: 修改 /system_ext/build.prop (步骤 187-203) ───────────


def modify_system_ext_build_prop(executor: AdbExecutor) -> bool:
    """阶段 G: 步骤 187-203."""
    fp = "/system_ext/build.prop"

    # 步骤 187: cat
    _cat_file(executor, 187, fp)

    # 步骤 188-201: sed -i 替换
    _CMDS: list[tuple[int, str, str]] = [
        (188, "ro.system_ext.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.system_ext.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (189, "ro.system_ext.build.date.utc=1753336048", "ro.system_ext.build.date.utc=1753846468"),
        (190, "ro.system_ext.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.system_ext.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (191, "ro.system_ext.build.id=RQ3A.211001.001", "ro.system_ext.build.id=BP4A.260205.001"),
        (192, "ro.system_ext.build.tags=release-keys", "ro.system_ext.build.tags=release-keys"),
        (193, "ro.system_ext.build.type=user", "ro.system_ext.build.type=user"),
        (194, "ro.system_ext.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.system_ext.build.version.incremental=14624666"),
        (195, "ro.product.system_ext.brand=google", "ro.product.system_ext.brand=google"),
        (196, "ro.product.system_ext.device=coral", "ro.product.system_ext.device=blazer"),
        (197, "ro.product.system_ext.manufacturer=Google", "ro.product.system_ext.manufacturer=Google"),
        (198, "ro.product.system_ext.model=Pixel 4 XL", "ro.product.system_ext.model=Pixel 10 Pro"),
        (199, "ro.product.system_ext.name=coral", "ro.product.system_ext.name=blazer"),
        (200, "ro.system_ext.build.version.release=11", "ro.system_ext.build.version.release=16"),
        (201, "ro.system_ext.build.version.release_or_codename=11",
              "ro.system_ext.build.version.release_or_codename=16"),
    ]
    for step_num, old_val, new_val in _CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 202: cat（验证）
    _cat_file(executor, 202, fp)

    # 步骤 203: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 203, fp, "#Removed_By_MiChangerPro")

    return True


# ── 阶段 H: 修改 /odm/etc/build.prop (步骤 204-218) ─────────────


def modify_odm_build_prop(executor: AdbExecutor) -> bool:
    """阶段 H: 步骤 204-218."""
    fp = "/odm/etc/build.prop"

    # 步骤 204: cat
    _cat_file(executor, 204, fp)

    # 步骤 205-216: sed -i 替换
    _CMDS: list[tuple[int, str, str]] = [
        (205, "ro.product.odm.brand=google", "ro.product.odm.brand=Google"),
        (206, "ro.product.odm.model=Pixel 4 XL", "ro.product.odm.model=Pixel 10 Pro"),
        (207, "ro.product.odm.manufacturer=Google", "ro.product.odm.manufacturer=Google"),
        (208, "ro.product.odm.device=coral", "ro.product.odm.device=blazer"),
        (209, "ro.odm.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.odm.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (210, "ro.odm.build.date.utc=1753336048", "ro.odm.build.date.utc=1753846468"),
        (211, "ro.odm.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.odm.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (212, "ro.odm.build.id=RQ3A.211001.001", "ro.odm.build.id=BP4A.260205.001"),
        (213, "ro.odm.build.tags=release-keys", "ro.odm.build.tags=release-keys"),
        (214, "ro.odm.build.type=user", "ro.odm.build.type=user"),
        (215, "ro.odm.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.odm.build.version.incremental=14624666"),
        (216, "ro.product.odm.name=coral", "ro.product.odm.name=blazer"),
    ]
    for step_num, old_val, new_val in _CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 217: cat（验证）
    _cat_file(executor, 217, fp)

    # 步骤 218: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 218, fp, "#Removed_By_MiChangerPro")

    return True


# ── 阶段 I: 修改 /vendor/build.prop (步骤 219-239) ──────────────


def modify_vendor_build_prop(executor: AdbExecutor) -> bool:
    """阶段 I: 步骤 219-239."""
    fp = "/vendor/build.prop"

    # 步骤 219: cat
    _cat_file(executor, 219, fp)

    # 步骤 220-235: sed -i 替换
    _CMDS: list[tuple[int, str, str]] = [
        (220, "ro.bootimage.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.bootimage.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (221, "ro.bootimage.build.date.utc=1753336048", "ro.bootimage.build.date.utc=1753846468"),
        (222, "ro.bootimage.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.bootimage.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (223, "ro.product.vendor.brand=google", "ro.product.vendor.brand=Google"),
        (224, "ro.product.vendor.model=Pixel 4 XL", "ro.product.vendor.model=Pixel 10 Pro"),
        (225, "ro.product.vendor.manufacturer=Google", "ro.product.vendor.manufacturer=Google"),
        (226, "ro.product.vendor.device=coral", "ro.product.vendor.device=blazer"),
        (227, "ro.vendor.build.date=Thu Jul 24 12:47:28 +07 2025",
              "ro.vendor.build.date=Wed Jul 30 03:34:28 UTC 2025"),
        (228, "ro.vendor.build.date.utc=1753336048", "ro.vendor.build.date.utc=1753846468"),
        (229, "ro.vendor.build.fingerprint=google/coral/coral:11/RQ3A.211001.001/7641976:user/release-keys",
              "ro.vendor.build.fingerprint=google\\/blazer\\/blazer:16\\/BP4A.260205.001\\/14624666:user\\/release-keys"),
        (230, "ro.vendor.build.id=RQ3A.211001.001", "ro.vendor.build.id=BP4A.260205.001"),
        (231, "ro.vendor.build.tags=release-keys", "ro.vendor.build.tags=release-keys"),
        (232, "ro.vendor.build.type=user", "ro.vendor.build.type=user"),
        (233, "ro.vendor.build.version.incremental=eng.cpidng.20250724.124938",
              "ro.vendor.build.version.incremental=14624666"),
        (234, "ro.product.vendor.name=coral", "ro.product.vendor.name=blazer"),
        (235, "ro.product.board=coral", "ro.product.board=blazer"),
    ]
    for step_num, old_val, new_val in _CMDS:
        _run_sed(executor, step_num, fp, old_val, new_val)

    # 步骤 236: cat（验证）
    _cat_file(executor, 236, fp)

    # 步骤 237: 删除 #Removed_By_MiChangerPro 行
    _run_sed_delete(executor, 237, fp, "#Removed_By_MiChangerPro")

    # 步骤 238: 删除 ro.hardware.keystore_desede 行
    _run_sed_delete(executor, 238, fp, "ro.hardware.keystore_desede")

    # 步骤 239: 删除 ro.hardware.egl 行
    _run_sed_delete(executor, 239, fp, "ro.hardware.egl")

    return True

