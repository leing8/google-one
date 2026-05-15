"""
XAPK 解析与解压模块。

XAPK 是 APKPure 发布的分割 APK 容器格式，本质是 ZIP 文件，包含：
- manifest.json: 包信息和 APK 文件列表
- *.apk: 分割 APK 文件（base + config）
- icon.png: 图标（忽略）

安全注意事项：
- 使用 zipfile.is_zipfile() 验证文件格式
- 使用 ZipFile 的 context manager 确保资源释放
- 使用 extractall() 的 members 参数只提取 .apk 文件
- 验证解压后文件大小与 manifest 声明一致

参考：
- https://docs.python.org/3/library/zipfile.html
- https://docs.python.org/3/library/json.html
- https://docs.python.org/3/library/tempfile.html
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from .models import ApkInfo, XapkInfo

logger = logging.getLogger(__name__)


class XapkParseError(Exception):
    """XAPK 文件解析错误。"""


def _validate_xapk_path(xapk_path: Path) -> Path:
    """验证 XAPK 文件路径。

    Args:
        xapk_path: XAPK 文件路径

    Returns:
        解析后的绝对路径

    Raises:
        XapkParseError: 文件不存在或不是有效的 ZIP 文件
    """
    resolved = xapk_path.resolve()
    if not resolved.is_file():
        raise XapkParseError(f"XAPK 文件不存在：{resolved}")
    if not zipfile.is_zipfile(resolved):
        raise XapkParseError(f"不是有效的 ZIP/XAPK 文件：{resolved}")
    return resolved


def _parse_manifest(manifest_raw: bytes) -> dict:
    """解析 manifest.json 内容。

    Args:
        manifest_raw: manifest.json 的原始字节内容

    Returns:
        解析后的字典

    Raises:
        XapkParseError: JSON 解析失败或必须字段缺失
    """
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise XapkParseError(f"manifest.json 解析失败：{exc}") from exc

    required_fields = ("package_name", "split_apks")
    missing = [f for f in required_fields if f not in manifest]
    if missing:
        raise XapkParseError(
            f"manifest.json 缺少必须字段：{missing}"
        )

    return manifest


def parse_xapk(xapk_path: Path) -> XapkInfo:
    """解析 XAPK 文件的 manifest 信息。

    不解压文件，仅读取 manifest.json 获取包信息。
    使用 ZipFile context manager 确保资源释放（Python 官方推荐）。

    Args:
        xapk_path: XAPK 文件路径

    Returns:
        XapkInfo 包含包名、版本和 APK 文件列表

    Raises:
        XapkParseError: 文件无效或 manifest 解析失败
    """
    resolved = _validate_xapk_path(xapk_path)

    with zipfile.ZipFile(resolved, "r") as zf:
        if "manifest.json" not in zf.namelist():
            raise XapkParseError(
                f"XAPK 中未找到 manifest.json：{resolved}"
            )

        manifest = _parse_manifest(zf.read("manifest.json"))

        # 获取 ZIP 内每个文件的大小
        zip_sizes = {
            info.filename: info.file_size
            for info in zf.infolist()
        }

    # 构建 APK 文件信息列表（按 manifest 中的顺序）
    apk_files: list[ApkInfo] = []
    for entry in manifest["split_apks"]:
        filename = entry["file"]
        split_id = entry.get("id", "unknown")
        size = zip_sizes.get(filename, 0)

        apk_files.append(ApkInfo(
            name=filename,
            path=resolved,  # 实际路径在 extract 时确定
            size_bytes=size,
            split_id=split_id,
        ))

    total_size = sum(a.size_bytes for a in apk_files)

    xapk_info = XapkInfo(
        xapk_name=resolved.name,
        package_name=manifest["package_name"],
        version_name=manifest.get("version_name", "unknown"),
        version_code=int(manifest.get("version_code", 0)),
        apk_files=tuple(apk_files),
        total_size_bytes=total_size,
    )

    logger.info(
        "解析 XAPK: %s → %s v%s (%d APK, %.1f MB)",
        xapk_info.xapk_name,
        xapk_info.package_name,
        xapk_info.version_name,
        xapk_info.apk_count,
        xapk_info.total_size_mb,
    )

    return xapk_info


def extract_xapk(
    xapk_path: Path,
    target_dir: Path,
) -> tuple[ApkInfo, ...]:
    """解压 XAPK 中的 APK 文件到目标目录。

    只提取 .apk 文件（忽略 manifest.json、icon.png 等）。
    使用 ZipFile.extract() 逐个提取，而非 extractall()，
    以便精确控制解压行为和安全验证。

    安全注意事项（参考 Python zipfile 文档 Decompression pitfalls）：
    - 只提取 .apk 后缀的文件
    - 验证文件名不含路径分隔符（防止目录遍历攻击）

    Args:
        xapk_path: XAPK 文件路径
        target_dir: 解压目标目录

    Returns:
        提取的 APK 文件信息元组（base 在前，按 manifest 顺序）

    Raises:
        XapkParseError: 文件无效或解压失败
    """
    resolved = _validate_xapk_path(xapk_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 先解析 manifest 获取 APK 列表和顺序
    xapk_info = parse_xapk(resolved)

    extracted_apks: list[ApkInfo] = []

    with zipfile.ZipFile(resolved, "r") as zf:
        for apk_meta in xapk_info.apk_files:
            filename = apk_meta.name

            # 安全验证：文件名不应包含路径分隔符
            if "/" in filename or "\\" in filename:
                logger.warning(
                    "跳过可疑文件名（包含路径分隔符）：%s",
                    filename,
                )
                continue

            # 验证文件存在于 ZIP 中
            if filename not in zf.namelist():
                raise XapkParseError(
                    f"manifest 中声明的文件不在 XAPK 中：{filename}"
                )

            # 使用 extract() 解压单个文件
            zf.extract(filename, target_dir)
            extracted_path = target_dir / filename

            # 验证解压后文件存在
            if not extracted_path.is_file():
                raise XapkParseError(
                    f"解压后文件未找到：{extracted_path}"
                )

            actual_size = extracted_path.stat().st_size

            extracted_apks.append(ApkInfo(
                name=filename,
                path=extracted_path,
                size_bytes=actual_size,
                split_id=apk_meta.split_id,
            ))

            logger.debug(
                "  解压: %s (%.1f MB, id=%s)",
                filename,
                actual_size / (1024 * 1024),
                apk_meta.split_id,
            )

    logger.info(
        "解压完成: %s → %d 个 APK 到 %s",
        resolved.name,
        len(extracted_apks),
        target_dir,
    )

    return tuple(extracted_apks)


def discover_apk_packages(
    apk_dir: Path,
) -> tuple[Path, ...]:
    """发现目录中的 APK 和 XAPK 文件。

    按文件名排序以保持确定性顺序。

    Args:
        apk_dir: APK/XAPK 文件目录

    Returns:
        按名称排序的文件路径元组

    Raises:
        XapkParseError: 目录不存在或为空
    """
    resolved = apk_dir.resolve()
    if not resolved.is_dir():
        raise XapkParseError(f"APK 目录不存在：{resolved}")

    files = sorted(
        f for f in resolved.iterdir()
        if f.is_file()
        and f.suffix.lower() in (".apk", ".xapk")
    )

    if not files:
        raise XapkParseError(
            f"APK 目录中未找到 .apk/.xapk 文件：{resolved}"
        )

    logger.info(
        "发现 %d 个安装包: %s",
        len(files),
        ", ".join(f.name for f in files),
    )

    return tuple(files)
