"""parse_pcapng — 解析 USBPcap 抓包文件并输出完整命令序列。

CLI 入口，将解析结果输出到 output/ 目录：
    - commands.txt         命令序列报告（人类可读）
    - commands_detail.txt  详细报告（含所有 ADB 消息）
    - transferred_files/   文件传输还原（完整原始文件）

用法:
    python parse_pcapng.py <pcapng_file>

示例:
    python parse_pcapng.py "WiresharkLog/5.0-Install Magisk && Root Phone/5.0-Install Magisk && Root Phone.pcapng"
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from adb_protocol import parse_pcapng
from parse_models import (
    CommandType,
    Direction,
    ParseResult,
)

logger = logging.getLogger(__name__)

# ── 输出目录 ───────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent
_OUTPUT_DIR = _PROJECT_ROOT / "output"


# ── 格式化工具 ─────────────────────────────────────────────────────


def _separator(char: str = "=", width: int = 80) -> str:
    """生成分隔线。"""
    return char * width


def _format_command_type(cmd_type: CommandType) -> str:
    """格式化命令类型标签。"""
    labels = {
        CommandType.REBOOT: "ADB Reboot",
        CommandType.SHELL: "ADB Shell",
        CommandType.SHELL_V2: "ADB Shell (v2)",
        CommandType.PUSH: "ADB Push (Sync)",
        CommandType.PULL: "ADB Pull (Sync)",
        CommandType.CONNECT: "ADB Connect",
    }
    return labels.get(cmd_type, cmd_type.value)


def _format_bytes(size: int) -> str:
    """格式化字节大小。"""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


# ── 报告生成 ───────────────────────────────────────────────────────


def _write_summary_report(result: ParseResult, output_dir: Path) -> Path:
    """生成命令序列汇总报告。

    参数:
        result: 解析结果。
        output_dir: 输出目录。

    返回:
        报告文件路径。
    """
    report_path = output_dir / "commands.txt"

    lines: list[str] = []
    lines.append(_separator("="))
    lines.append("  pcapng 解析报告 — 命令序列汇总")
    lines.append(_separator("="))
    lines.append("")
    lines.append(f"源文件:       {result.source_file}")
    lines.append(f"USB 帧总数:   {result.total_usb_frames}")
    lines.append(f"ADB 消息总数: {result.total_adb_messages}")
    lines.append(f"命令总数:     {len(result.commands)}")
    lines.append(f"生成时间:     {datetime.now().isoformat()}")
    lines.append("")

    # 连接信息
    lines.append(_separator("-"))
    lines.append("  连接信息")
    lines.append(_separator("-"))
    lines.append(f"设备 Banner:  {result.connection.device_banner}")
    lines.append(f"主机特性:     {', '.join(result.connection.host_features[:5])}...")
    lines.append(
        f"设备特性:     {', '.join(result.connection.device_features[:5])}..."
    )
    lines.append("")

    # 命令序列总览
    lines.append(_separator("-"))
    lines.append("  命令序列总览")
    lines.append(_separator("-"))
    lines.append("")

    for cmd in result.commands:
        file_info = ""
        if cmd.file_transfer:
            file_info = f"  [{_format_bytes(cmd.file_transfer.file_size)}]"
        lines.append(
            f"  步骤 {cmd.step}: [{_format_command_type(cmd.command_type)}] "
            f"{cmd.command}{file_info}"
        )

    lines.append("")

    # 命令详情
    lines.append(_separator("="))
    lines.append("  命令详情")
    lines.append(_separator("="))

    for cmd in result.commands:
        lines.append("")
        lines.append(_separator("-"))
        lines.append(
            f"  步骤 {cmd.step}: {_format_command_type(cmd.command_type)}"
        )
        lines.append(_separator("-"))
        lines.append(f"命令:     {cmd.command}")
        lines.append(
            f"Stream:   local_id={cmd.stream.local_id}, "
            f"remote_id={cmd.stream.remote_id}"
        )
        lines.append(f"消息数:   {len(cmd.stream.messages)}")

        if cmd.file_transfer:
            ft = cmd.file_transfer
            lines.append(f"文件传输: {ft.remote_path}")
            lines.append(f"捕获大小: {_format_bytes(ft.file_size)} ({ft.file_size} bytes)")
            # 输出到 transferred_files 目录
            file_name = Path(ft.remote_path).name
            lines.append(f"还原文件: transferred_files/{file_name}")
            lines.append(
                f"注意:     USBPcap 抓包 snaplen=65535 截断了大文件传输数据，"
                f"还原文件为部分捕获数据"
            )
            # 检查原始文件是否存在
            orig_file = (
                Path(result.source_file).parent / file_name
            )
            if orig_file.exists():
                lines.append(
                    f"原始文件: {orig_file.name} "
                    f"({_format_bytes(orig_file.stat().st_size)})"
                )

        if cmd.output:
            lines.append("")
            lines.append("输出:")
            for line in cmd.output.splitlines():
                lines.append(f"  | {line}")

    lines.append("")
    lines.append(_separator("="))
    lines.append("  报告结束")
    lines.append(_separator("="))

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")

    logger.info("汇总报告: %s", report_path)
    return report_path


def _write_detail_report(result: ParseResult, output_dir: Path) -> Path:
    """生成详细报告（含所有 ADB 消息）。

    参数:
        result: 解析结果。
        output_dir: 输出目录。

    返回:
        报告文件路径。
    """
    report_path = output_dir / "commands_detail.txt"

    lines: list[str] = []
    lines.append(_separator("="))
    lines.append("  pcapng 解析报告 — 详细 ADB 消息")
    lines.append(_separator("="))
    lines.append("")

    for cmd in result.commands:
        lines.append(_separator("-"))
        lines.append(
            f"  步骤 {cmd.step}: [{_format_command_type(cmd.command_type)}] "
            f"{cmd.command}"
        )
        lines.append(_separator("-"))
        lines.append("")

        for msg in cmd.stream.messages:
            dir_str = "OUT" if msg.direction == Direction.OUT else "IN "
            cmd_name = msg.command.value

            # 载荷预览
            payload_preview = ""
            if msg.payload:
                if msg.data_length <= 200:
                    safe = msg.payload.decode("utf-8", errors="replace")
                    # 清理不可打印字符
                    safe = "".join(
                        c if c.isprintable() or c in "\n\r\t" else f"\\x{ord(c):02x}"
                        for c in safe
                    )
                    payload_preview = f" | {safe[:200]}"
                else:
                    payload_preview = (
                        f" | [{_format_bytes(msg.data_length)} data]"
                    )

            lines.append(
                f"  [Frame {msg.frame_number:5d}] {dir_str} {cmd_name} "
                f"arg0={msg.arg0} arg1={msg.arg1} "
                f"len={msg.data_length}{payload_preview}"
            )

        lines.append("")

    lines.append(_separator("="))

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")

    logger.info("详细报告: %s", report_path)
    return report_path


def _save_transferred_files(
    result: ParseResult,
    output_dir: Path,
) -> list[Path]:
    """保存文件传输中还原的完整原始文件。

    参数:
        result: 解析结果。
        output_dir: 输出目录。

    返回:
        保存的文件路径列表。
    """
    files_dir = output_dir / "transferred_files"
    saved: list[Path] = []

    for cmd in result.commands:
        if cmd.file_transfer is None:
            continue

        ft = cmd.file_transfer
        file_name = Path(ft.remote_path).name

        if not file_name:
            file_name = f"unknown_step{cmd.step}.bin"

        files_dir.mkdir(parents=True, exist_ok=True)
        file_path = files_dir / file_name
        file_path.write_bytes(ft.file_data)

        saved.append(file_path)
        logger.info(
            "还原文件: %s (%s)",
            file_path,
            _format_bytes(ft.file_size),
        )

    return saved


# ── CLI 入口 ───────────────────────────────────────────────────────


def main() -> None:
    """解析 pcapng 文件并输出结果。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 参数处理
    if len(sys.argv) < 2:
        # 默认文件
        pcapng_path = (
            _PROJECT_ROOT
            / "WiresharkLog"
            / "7.0-Randomly change device"
            / "7.0-Randomly change device.pcapng"
        )
    else:
        pcapng_path = Path(sys.argv[1])

    if not pcapng_path.exists():
        logger.error("文件不存在: %s", pcapng_path)
        sys.exit(1)

    # 创建输出目录
    output_dir = _OUTPUT_DIR / pcapng_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("解析文件: %s", pcapng_path)
    logger.info("输出目录: %s", output_dir)

    # 执行解析
    result = parse_pcapng(pcapng_path)

    # 生成报告
    summary_path = _write_summary_report(result, output_dir)
    detail_path = _write_detail_report(result, output_dir)

    # 保存还原文件
    saved_files = _save_transferred_files(result, output_dir)

    # 打印最终汇总
    print()
    print(_separator("="))
    print("  解析完成")
    print(_separator("="))
    print(f"  源文件:       {pcapng_path.name}")
    print(f"  USB 帧:       {result.total_usb_frames}")
    print(f"  ADB 消息:     {result.total_adb_messages}")
    print(f"  命令数:       {len(result.commands)}")
    print()

    for cmd in result.commands:
        file_info = ""
        if cmd.file_transfer:
            file_info = f"  [{_format_bytes(cmd.file_transfer.file_size)}]"
        print(
            f"  步骤 {cmd.step}: [{_format_command_type(cmd.command_type)}] "
            f"{cmd.command}{file_info}"
        )

    print()
    print(f"  汇总报告: {summary_path}")
    print(f"  详细报告: {detail_path}")

    if saved_files:
        print(f"  还原文件: {len(saved_files)} 个")
        for f in saved_files:
            print(f"    - {f.name} ({_format_bytes(f.stat().st_size)})")

    print(_separator("="))


if __name__ == "__main__":
    main()
