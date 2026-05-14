"""XAPK 文件提取器。

从 XAPK（ZIP 格式）中提取 base APK 和 split APK 文件，
并解析 manifest.json 获取包名、版本等元数据。

XAPK 文件结构:
    Play Integrity API Checker_2.2_APKPure.xapk (ZIP)
    ├── manifest.json          ← 应用元数据（包名、版本等）
    ├── gr.nikolasspyr.integritycheck.apk  ← base APK (id="base")
    ├── config.en.apk          ← split APK (id="config.en")
    ├── config.fr.apk          ← split APK (id="config.fr")
    ├── config.mdpi.apk        ← split APK (id="config.mdpi")
    ├── icon.png               ← 图标（不需要提取）
    └── ...

Python 官方最佳实践:
    - zipfile.ZipFile 作为 context manager 使用（Python 3.14 文档推荐）
    - zipfile.is_zipfile() 验证文件格式
    - zipfile.ZipFile.extract() 逐个提取成员
    - json.loads() 解析 manifest.json
    - pathlib.Path 用于路径操作
    - dataclasses(frozen=True) 实现不可变数据模型
    - tempfile.mkdtemp() 创建安全的临时目录

参考:
    https://docs.python.org/3/library/zipfile.html
    https://docs.python.org/3/library/json.html
    https://docs.python.org/3/library/tempfile.html
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# manifest.json 中标识 base APK 的 id 值
_BASE_APK_ID: str = "base"

# manifest.json 文件名
_MANIFEST_NAME: str = "manifest.json"


@dataclass(frozen=True)
class SplitApkEntry:
    """XAPK manifest.json 中的单个 split_apks 条目。

    严格对应 manifest.json 的 split_apks 数组元素:
        {"file": "gr.nikolasspyr.integritycheck.apk", "id": "base"}

    属性:
        file: XAPK 内的文件名。
        apk_id: APK 标识（"base" 或 "config.xxx"）。
        is_base: 是否为 base APK。
    """

    file: str
    apk_id: str
    is_base: bool


@dataclass(frozen=True)
class XapkManifest:
    """XAPK manifest.json 解析结果。

    属性:
        package_name: 应用包名（例如 "gr.nikolasspyr.integritycheck"）。
        name: 应用显示名称（例如 "Play Integrity API Checker"）。
        version_name: 版本号（例如 "2.2"）。
        version_code: 版本代码（例如 "22"）。
        split_apks: 所有 APK 条目（base + splits）。
    """

    package_name: str
    name: str
    version_name: str
    version_code: str
    split_apks: tuple[SplitApkEntry, ...]


@dataclass(frozen=True)
class ExtractedApk:
    """提取到本地磁盘的单个 APK 文件信息。

    属性:
        local_path: 提取后的本地文件路径。
        original_name: XAPK 内的原始文件名。
        apk_id: APK 标识（"base" 或 "config.xxx"）。
        is_base: 是否为 base APK。
        size: 文件大小（字节）。
    """

    local_path: Path
    original_name: str
    apk_id: str
    is_base: bool
    size: int


@dataclass(frozen=True)
class XapkContent:
    """XAPK 文件完整提取结果。

    属性:
        xapk_path: XAPK 源文件路径。
        manifest: 解析后的 manifest 数据。
        extracted_apks: 按 manifest.json split_apks 顺序排列的已提取 APK 列表。
        extract_dir: 提取目标目录。
    """

    xapk_path: Path
    manifest: XapkManifest
    extracted_apks: tuple[ExtractedApk, ...]
    extract_dir: Path


class XapkError(Exception):
    """XAPK 提取过程中的错误。"""


# ── manifest.json 解析 ─────────────────────────────────────────────


def _parse_manifest(raw: bytes) -> XapkManifest:
    """解析 manifest.json 原始字节为 XapkManifest。

    严格按照 XAPK manifest.json 格式解析:
        {
            "package_name": "gr.nikolasspyr.integritycheck",
            "name": "Play Integrity API Checker",
            "version_name": "2.2",
            "version_code": "22",
            "split_apks": [
                {"file": "gr.nikolasspyr.integritycheck.apk", "id": "base"},
                {"file": "config.mdpi.apk", "id": "config.mdpi"},
                ...
            ]
        }

    参数:
        raw: manifest.json 的原始字节内容。

    返回:
        解析后的 XapkManifest。

    抛出:
        XapkError: 如果 JSON 格式无效或缺少必需字段。
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        msg = f"manifest.json 解析失败: {e}"
        logger.error(msg)
        raise XapkError(msg) from e

    # 验证必需字段
    required_fields = ("package_name", "name", "version_name", "version_code", "split_apks")
    for field in required_fields:
        if field not in data:
            msg = f"manifest.json 缺少必需字段: {field}"
            logger.error(msg)
            raise XapkError(msg)

    # 解析 split_apks 数组
    split_apks: list[SplitApkEntry] = []
    for entry in data["split_apks"]:
        if "file" not in entry or "id" not in entry:
            msg = f"split_apks 条目缺少 file 或 id 字段: {entry}"
            logger.error(msg)
            raise XapkError(msg)

        split_apks.append(
            SplitApkEntry(
                file=entry["file"],
                apk_id=entry["id"],
                is_base=(entry["id"] == _BASE_APK_ID),
            )
        )

    if not split_apks:
        msg = "manifest.json 中 split_apks 为空"
        logger.error(msg)
        raise XapkError(msg)

    return XapkManifest(
        package_name=data["package_name"],
        name=data["name"],
        version_name=data["version_name"],
        version_code=data["version_code"],
        split_apks=tuple(split_apks),
    )


# ── XAPK 提取 ─────────────────────────────────────────────────────


def extract_xapk(
    xapk_path: Path,
    output_dir: Path | None = None,
) -> XapkContent:
    """从 XAPK 文件提取所有 APK 和元数据。

    Python 官方推荐:
    - 使用 zipfile.is_zipfile() 验证文件格式
    - 使用 ZipFile 的 context manager 模式确保资源释放
    - 使用 ZipFile.extract() 逐个安全提取成员
    - 使用 tempfile.mkdtemp() 创建安全的临时目录

    参数:
        xapk_path: XAPK 文件路径。
        output_dir: 提取目标目录。如果为 None，使用 tempfile.mkdtemp()。

    返回:
        包含 manifest 和所有已提取 APK 信息的 XapkContent。

    抛出:
        XapkError: 如果文件不存在、格式无效或提取失败。
    """
    resolved_path = Path(xapk_path).resolve()

    # 验证文件存在性（Python pathlib 推荐）
    if not resolved_path.exists():
        msg = f"XAPK 文件不存在: {resolved_path}"
        logger.error(msg)
        raise XapkError(msg)

    if not resolved_path.is_file():
        msg = f"路径不是文件: {resolved_path}"
        logger.error(msg)
        raise XapkError(msg)

    # Python zipfile 官方推荐: 使用 is_zipfile() 验证
    if not zipfile.is_zipfile(resolved_path):
        msg = f"文件不是有效的 ZIP/XAPK 格式: {resolved_path}"
        logger.error(msg)
        raise XapkError(msg)

    # 确定提取目录
    if output_dir is not None:
        extract_dir = Path(output_dir).resolve()
        extract_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Python tempfile 官方推荐: 使用 mkdtemp() 创建安全临时目录
        extract_dir = Path(tempfile.mkdtemp(prefix="xapk_"))

    logger.info("XAPK 文件: %s", resolved_path)
    logger.info("提取目录: %s", extract_dir)

    # Python zipfile 官方推荐: 使用 context manager 确保资源释放
    with zipfile.ZipFile(resolved_path, "r") as zf:
        # 列出 XAPK 内所有成员
        members = zf.namelist()
        logger.info("XAPK 内文件 (%d 个):", len(members))
        for m in members:
            info = zf.getinfo(m)
            logger.info("  %s (%d bytes)", m, info.file_size)

        # 读取并解析 manifest.json
        if _MANIFEST_NAME not in members:
            msg = f"XAPK 中未找到 {_MANIFEST_NAME}"
            logger.error(msg)
            raise XapkError(msg)

        manifest_raw = zf.read(_MANIFEST_NAME)
        manifest = _parse_manifest(manifest_raw)

        logger.info("包名: %s", manifest.package_name)
        logger.info("应用: %s v%s", manifest.name, manifest.version_name)
        logger.info("APK 条目 (%d 个):", len(manifest.split_apks))
        for entry in manifest.split_apks:
            role = "base" if entry.is_base else "split"
            logger.info("  [%s] %s (%s)", role, entry.file, entry.apk_id)

        # 逐个提取 APK 文件（严格按照 manifest.json 中 split_apks 顺序）
        extracted: list[ExtractedApk] = []

        for entry in manifest.split_apks:
            if entry.file not in members:
                msg = f"XAPK 中未找到 manifest 声明的 APK: {entry.file}"
                logger.error(msg)
                raise XapkError(msg)

            # Python zipfile 官方推荐: 使用 extract() 安全提取单个成员
            zf.extract(entry.file, path=extract_dir)

            local_path = extract_dir / entry.file
            file_size = local_path.stat().st_size

            extracted.append(
                ExtractedApk(
                    local_path=local_path,
                    original_name=entry.file,
                    apk_id=entry.apk_id,
                    is_base=entry.is_base,
                    size=file_size,
                )
            )

            logger.info(
                "  提取: %s → %s (%d bytes)",
                entry.file,
                local_path,
                file_size,
            )

    logger.info("XAPK 提取完成: %d 个 APK", len(extracted))

    return XapkContent(
        xapk_path=resolved_path,
        manifest=manifest,
        extracted_apks=tuple(extracted),
        extract_dir=extract_dir,
    )
