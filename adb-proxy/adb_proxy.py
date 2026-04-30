r"""
ADB Proxy — adb 劫持代理

功能
====
1. 透明转发：所有 adb 调用原封不动转发给同目录下的 adb_real.exe
2. 命令日志：每条调用记录到 Documents\adb\<日期>.log，每行一条原始命令
3. 文件备份：push / pull / install 类命令执行时，
   将本地源文件异步复制到 Documents\adb\backup\<子命令>\

目录结构
========
Documents\
└── adb\
    ├── <日期>.log      ← 每条 adb 调用一行
    └── backup\         ← 文件传输命令的本地源文件备份
        ├── push\       ← push 命令源文件
        ├── pull\       ← pull 命令目标文件
        ├── install\    ← install / install-multiple / install-multi-package 源 APK
        └── ...

日志格式
========
每行格式：YYYY-MM-DD HH:MM:SS  adb <原始参数>

不记录返回码、stdout、stderr、异常 —— 只记录原始调用。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 所有文件统一存放在用户文档目录下的 adb 文件夹中
_ADB_ROOT_DIR: Path = Path.home() / "Documents" / "adb"

# adb 官方文档中定义的涉及文件传输的子命令
# 参考：https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/master/docs/user/adb.1.md
_FILE_TRANSFER_SUBCOMMANDS: frozenset[str] = frozenset({
    "push",
    "pull",
    "sync",
    "install",
    "install-multiple",
    "install-multi-package",
})


# ---------------------------------------------------------------------------
# 日志记录器
# ---------------------------------------------------------------------------

class AdbCommandLogger:
    """
    将每条 adb 调用原封不动地追加到日志文件。

    日志文件路径：Documents/adb/<日期>.log
    每行格式：YYYY-MM-DD HH:MM:SS  adb <原始参数>

    不做任何解析、分类、结果记录 —— 收到什么记什么。
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._today_path: Path | None = None

    def _ensure_log_file(self) -> Path:
        """确保当日日志文件存在，返回其路径。"""
        today = datetime.now().strftime("%Y-%m-%d")
        path = self._root_dir / f"{today}.log"
        if path != self._today_path:
            self._root_dir.mkdir(parents=True, exist_ok=True)
            self._today_path = path
        return path

    def write(self, raw_args: list[str]) -> None:
        """
        将原始调用作为一行追加到当日日志文件。

        参数：
            raw_args: sys.argv[1:]，即 adb 后的所有参数
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cmd_str = " ".join(raw_args) if raw_args else ""
        line = f"{timestamp}  adb {cmd_str}\n"
        with open(self._ensure_log_file(), "a", encoding="utf-8") as fh:
            fh.write(line)


# ---------------------------------------------------------------------------
# 本地文件路径提取（仅在文件传输命令中使用）
# ---------------------------------------------------------------------------

# adb 官方文档定义的需要单独传参的全局选项
# 参考：https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/master/docs/user/adb.1.md
_OPTION_WITH_ARG: frozenset[str] = frozenset(("-s", "-t", "-H", "-P", "-L"))


def _skip_global_options(args: list[str]) -> tuple[str, int]:
    """
    从参数列表中跳过 adb 全局选项，找到子命令及其索引。

    处理情况：
    - 合并写法：-sSERIAL（以 - 开头，整个 arg 是选项+值）
    - 分开写法：-s SERIAL（SERIAL 单独一个 arg）
    - 长选项：--forward, --one-device=SERIAL

    返回：
        (子命令名称, 子命令在 raw_args 中的索引)
        如果没有子命令则返回 ("", -1)
    """
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            # 第一个不以 - 开头的参数即为子命令
            return arg, i
        # 处理以 - 开头的选项
        if arg.startswith("--"):
            if "=" in arg:
                i += 1  # --key=value，视为已消费
            else:
                i += 1
                # 长选项后可能跟独立参数值
                if i < len(args) and not args[i].startswith("-"):
                    i += 1
        elif len(arg) > 2:
            # 合并写法：-sSERIAL、-Hlocalhost —— 值合并在同一 arg 中
            i += 1
        elif arg in _OPTION_WITH_ARG:
            # 分开写法：-s SERIAL —— 跳过选项后再跳一个参数值
            i += 2
        else:
            # 独立选项如 -v、-a，没有后续值
            i += 1
    return "", -1


def _is_file_transfer(raw_args: list[str]) -> bool:
    """
    判断是否为文件传输类命令。

    正确跳过 adb 全局选项（如 -s SERIAL 或 -sSERIAL），
    找到真正的子命令后再判断。
    """
    sub, _ = _skip_global_options(raw_args)
    return sub in _FILE_TRANSFER_SUBCOMMANDS


def _extract_local_paths(raw_args: list[str], cwd: Path) -> list[Path]:
    """
    从文件传输命令中提取本地源文件/目录路径。

    各命令参数布局（跳过子命令后的选项后）：

    ========= ============================
    命令       参数布局
    ========= ============================
    push      LOCAL... REMOTE（最后一个为远程路径，前面的均为本地源）
    pull      REMOTE... LOCAL（最后一个为本地路径）
    install   [-flags] APK...
    install-* [-flags] PKG... PARTITION
    sync      [PARTITION]（无本地文件，无需处理）
    ========= ============================

    所有路径相对于 cwd 解析，仅返回本地存在的文件/目录。
    """
    if not raw_args:
        return []

    base = cwd.resolve()

    # 正确跳过全局选项，找到子命令及其索引
    sub, sub_idx = _skip_global_options(raw_args)
    if sub == "" or sub not in _FILE_TRANSFER_SUBCOMMANDS:
        return []

    after_sub = raw_args[sub_idx + 1:]
    remaining = _strip_command_options(after_sub)

    if sub == "push":
        return _push_local_paths(remaining, base)
    if sub == "pull":
        return _pull_local_path(remaining, base)
    if sub in ("install", "install-multiple", "install-multi-package"):
        return _install_local_paths(remaining, base)
    return []


def _strip_command_options(args: list[str]) -> list[str]:
    """
    从参数列表中跳过选项标志，只保留实际路径参数。

    处理情况：
    - 独立选项：-v、-a
    - 带合并值的选项：-sSERIAL、-t42
    - 带独立值的选项：-s SERIAL
    - 长选项：--forward、--one-device=SERIAL
    """
    OPTION_WITH_ARG = _OPTION_WITH_ARG
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            break
        if arg.startswith("--"):
            if "=" in arg:
                i += 1
            else:
                i += 1
                if i < len(args) and not args[i].startswith("-"):
                    i += 1
        elif arg.lstrip("-") and not arg.lstrip("-").startswith("-"):
            i += 1
        elif arg in OPTION_WITH_ARG:
            i += 2
        else:
            i += 1
    return args[i:]


def _push_local_paths(args: list[str], base: Path) -> list[Path]:
    """push: 最后一个参数是远程路径，其前面的均为本地源。"""
    if len(args) < 2:
        return []
    return [p for arg in args[:-1] for p in [_resolve(arg, base)] if p.exists()]


def _pull_local_path(args: list[str], base: Path) -> list[Path]:
    """pull: 最后一个参数是本地目标路径，备份它（如果存在）。"""
    if not args:
        return []
    p = _resolve(args[-1], base)
    return [p] if p.exists() else []


def _install_local_paths(args: list[str], base: Path) -> list[Path]:
    """install / install-*: 所有非选项且本地存在的文件。"""
    return [p for arg in args if not arg.startswith("-")
            for p in [_resolve(arg, base)] if p.exists() and p.is_file()]


def _resolve(arg: str, base: Path) -> Path:
    """将参数解析为绝对路径。处理引号、相对路径、绝对路径。"""
    cleaned = arg.strip('"').strip("'")
    p = Path(cleaned)
    if p.is_absolute():
        return p
    return base / p


# ---------------------------------------------------------------------------
# 异步文件复制器
# ---------------------------------------------------------------------------

class AsyncFileCopier:
    """
    将文件传输命令的本地源文件/目录异步复制到备份目录。

    备份目录结构：
        Documents/adb/backup/<子命令>/<原文件名>_<时间戳>[_<扩展名>]

    示例：
        Documents/adb/backup/push/myfile_20260424_143055_123456.txt
        Documents/adb/backup/install/app_20260424_143100_654321.apk
    """

    _lock = asyncio.Lock()

    def __init__(self, backup_dir: Path) -> None:
        self._backup_dir = backup_dir

    @staticmethod
    def _timestamp() -> str:
        """生成时间戳字符串，精确到微秒，保证文件名唯一。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    @staticmethod
    def _subcommand(raw_args: list[str]) -> str:
        """从 raw_args 中提取文件传输子命令名称。"""
        for arg in raw_args:
            if not arg.startswith("-") and arg in _FILE_TRANSFER_SUBCOMMANDS:
                return arg
        return "unknown"

    async def copy(self, raw_args: list[str], cwd: Path) -> list[Path]:
        """
        异步复制所有本地源文件/目录。

        参数：
            raw_args: 原始 adb 参数
            cwd: 调用者工作目录（用于解析相对路径）

        返回：
            复制成功的目标路径列表
        """
        sources = _extract_local_paths(raw_args, cwd)
        if not sources:
            return []

        ts = self._timestamp()
        sub = self._subcommand(raw_args)
        results: list[Path] = []

        for src in sources:
            dest = await self._copy_one(src, sub, ts)
            if dest is not None:
                results.append(dest)

        return results

    async def _copy_one(self, src: Path, sub: str, ts: str) -> Path | None:
        """异步复制单个文件或目录。"""
        async with self._lock:
            dest = self._destination(src, sub, ts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=False)
                else:
                    shutil.copy2(src, dest)
                return dest
            except OSError:
                return None

    def _destination(self, src: Path, sub: str, ts: str) -> Path:
        """构建备份目标路径。"""
        name = f"{src.stem}_{ts}{src.suffix}" if src.is_file() else f"{src.name}_{ts}"
        return self._backup_dir / sub / name


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------

def main() -> None:
    # 在子进程继承工作目录前，保存调用者的工作目录
    caller_cwd = Path.cwd()

    parser = argparse.ArgumentParser(
        prog="adb",
        description="ADB 劫持代理 — 透明转发 + 命令日志 + 文件备份",
        epilog=f"数据目录（日志和备份）：{_ADB_ROOT_DIR}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=_ADB_ROOT_DIR,
        help="数据根目录（默认：%(default)s）",
    )
    parsed_ns, raw_args = parser.parse_known_args()

    # 立即记录：收到什么记什么，不做任何解析
    logger = AdbCommandLogger(parsed_ns.root_dir)
    logger.write(raw_args)

    # 定位 adb_real.exe（与当前程序同目录）
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent
    adb_real = exe_dir / "adb_real.exe"

    # 执行真正的 adb，原样透传所有输出
    real_cmdline = [str(adb_real)] + raw_args
    try:
        proc = subprocess.Popen(
            real_cmdline,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        stdout_bytes, stderr_bytes = proc.communicate()
        ret_code = proc.returncode
    except FileNotFoundError:
        sys.stderr.write(f"找不到 adb_real.exe：{adb_real}\n")
        sys.exit(127)
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)

    # 透传 stdout / stderr
    if stdout_bytes:
        sys.stdout.buffer.write(stdout_bytes)
    if stderr_bytes:
        sys.stderr.buffer.write(stderr_bytes)

    # 文件传输命令：异步复制本地源文件
    if _is_file_transfer(raw_args):
        backup_dir = parsed_ns.root_dir
        asyncio.run(_async_backup(backup_dir, raw_args, caller_cwd))

    sys.exit(ret_code)


async def _async_backup(
    backup_dir: Path,
    raw_args: list[str],
    cwd: Path,
) -> None:
    """运行文件备份协程。异常静默忽略，不影响 adb 调用结果。"""
    try:
        copier = AsyncFileCopier(backup_dir)
        await copier.copy(raw_args, cwd)
    except Exception:
        pass


if __name__ == "__main__":
    main()
