"""
对比两个 pcapng 文件中解析出的 ADB 命令序列。

逐行对比每一条命令的：
1. 命令服务名 (service)
2. 命令类型 (command_type)
3. 命令内容 (command_detail)
4. 响应内容 (response_summary)
5. 时间信息 (timing)

输出差异报告。
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .pcapng_adb_parser import (
    ExtractedCommand,
    ParseResult,
    parse_pcapng,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 差异模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandDiff:
    """单条命令的差异。"""

    index: int
    field_name: str  # 差异字段
    file_a_value: str
    file_b_value: str


@dataclass(frozen=True)
class CommandComparison:
    """一对命令的比较结果。"""

    index: int
    service_a: str
    service_b: str
    identical: bool
    diffs: tuple[CommandDiff, ...]


@dataclass
class CompareResult:
    """完整对比结果。"""

    file_a: str
    file_b: str
    total_commands_a: int
    total_commands_b: int
    comparisons: list[CommandComparison] = field(default_factory=list)
    only_in_a: list[ExtractedCommand] = field(default_factory=list)
    only_in_b: list[ExtractedCommand] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 对比逻辑
# ---------------------------------------------------------------------------


def _compare_commands(
    idx: int,
    cmd_a: ExtractedCommand,
    cmd_b: ExtractedCommand,
) -> CommandComparison:
    """逐字段对比两条命令。"""
    diffs: list[CommandDiff] = []

    if cmd_a.service != cmd_b.service:
        diffs.append(CommandDiff(
            index=idx,
            field_name="service",
            file_a_value=cmd_a.service,
            file_b_value=cmd_b.service,
        ))

    if cmd_a.command_type != cmd_b.command_type:
        diffs.append(CommandDiff(
            index=idx,
            field_name="command_type",
            file_a_value=cmd_a.command_type,
            file_b_value=cmd_b.command_type,
        ))

    if cmd_a.command_detail != cmd_b.command_detail:
        diffs.append(CommandDiff(
            index=idx,
            field_name="command_detail",
            file_a_value=cmd_a.command_detail,
            file_b_value=cmd_b.command_detail,
        ))

    if cmd_a.response_summary != cmd_b.response_summary:
        diffs.append(CommandDiff(
            index=idx,
            field_name="response_summary",
            file_a_value=cmd_a.response_summary,
            file_b_value=cmd_b.response_summary,
        ))

    # 时间差异（只比较持续时间差异 > 1 秒）
    duration_a = cmd_a.end_time - cmd_a.start_time
    duration_b = cmd_b.end_time - cmd_b.start_time
    if abs(duration_a - duration_b) > 1.0:
        diffs.append(CommandDiff(
            index=idx,
            field_name="duration",
            file_a_value=f"{duration_a:.3f}s",
            file_b_value=f"{duration_b:.3f}s",
        ))

    return CommandComparison(
        index=idx,
        service_a=cmd_a.service,
        service_b=cmd_b.service,
        identical=len(diffs) == 0,
        diffs=tuple(diffs),
    )


def compare_results(
    result_a: ParseResult,
    result_b: ParseResult,
) -> CompareResult:
    """对比两个解析结果。"""
    compare = CompareResult(
        file_a=result_a.file_path,
        file_b=result_b.file_path,
        total_commands_a=len(result_a.commands),
        total_commands_b=len(result_b.commands),
    )

    min_len = min(len(result_a.commands), len(result_b.commands))

    for i in range(min_len):
        cmd_a = result_a.commands[i]
        cmd_b = result_b.commands[i]
        comparison = _compare_commands(i + 1, cmd_a, cmd_b)
        compare.comparisons.append(comparison)

    # 只在一侧存在的命令
    if len(result_a.commands) > min_len:
        compare.only_in_a = list(result_a.commands[min_len:])
    if len(result_b.commands) > min_len:
        compare.only_in_b = list(result_b.commands[min_len:])

    return compare


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 80) -> str:
    """截断文本。"""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def print_parse_result(result: ParseResult) -> None:
    """打印单个文件的解析结果。"""
    print(f"\n{'=' * 80}")
    print(f"文件: {Path(result.file_path).name}")
    print(f"{'=' * 80}")
    print(f"  USB 帧总数: {result.total_frames}")
    print(f"  ADB 消息数: {len(result.adb_messages)}")
    print(f"  ADB 会话数: {len(result.sessions)}")
    print(f"  提取命令数: {len(result.commands)}")
    print(f"  连接信息:   {_truncate(result.connection_info, 100)}")
    print()

    # 列出所有 ADB 消息（用于调试）
    print("  --- ADB 消息序列 ---")
    for msg in result.adb_messages:
        payload_preview = ""
        if msg.payload:
            try:
                text = msg.payload.rstrip(b"\x00").decode(
                    "utf-8", errors="replace"
                )
                payload_preview = _truncate(text, 60)
            except Exception:
                payload_preview = f"[{len(msg.payload)} bytes]"

        arrow = "→" if msg.direction == "host->device" else "←"
        print(
            f"  [Frame {msg.frame_no:4d}] "
            f"{msg.timestamp:10.3f}s "
            f"{arrow} {msg.command} "
            f"arg0={msg.arg0:#x} arg1={msg.arg1:#x} "
            f"len={msg.data_length} "
            f"{payload_preview}"
        )
    print()

    # 列出提取的命令
    print("  --- 提取的命令序列 ---")
    for cmd in result.commands:
        resp_preview = _truncate(
            cmd.response_summary.replace("\n", " | "), 70
        )
        print(
            f"  [{cmd.index}] [{cmd.command_type:10s}] "
            f"{cmd.command_detail}"
        )
        print(f"      响应: {resp_preview}")
        print(
            f"      时间: {cmd.start_time:.3f}s ~ "
            f"{cmd.end_time:.3f}s "
            f"(持续 {cmd.end_time - cmd.start_time:.3f}s)"
        )
    print()


def print_compare_result(compare: CompareResult) -> None:
    """打印对比结果。"""
    print(f"\n{'=' * 80}")
    print("对比结果")
    print(f"{'=' * 80}")
    print(f"  文件 A: {Path(compare.file_a).name}")
    print(f"  文件 B: {Path(compare.file_b).name}")
    print(f"  文件 A 命令数: {compare.total_commands_a}")
    print(f"  文件 B 命令数: {compare.total_commands_b}")
    print()

    identical_count = sum(
        1 for c in compare.comparisons if c.identical
    )
    diff_count = sum(
        1 for c in compare.comparisons if not c.identical
    )

    print(f"  ✅ 完全相同的命令: {identical_count}")
    print(f"  ❌ 有差异的命令:   {diff_count}")

    if compare.only_in_a:
        print(f"  ⚠️  仅在文件 A 中: {len(compare.only_in_a)}")
    if compare.only_in_b:
        print(f"  ⚠️  仅在文件 B 中: {len(compare.only_in_b)}")
    print()

    # 详细逐行对比
    print("  --- 逐行对比 ---")
    for comp in compare.comparisons:
        status = "✅" if comp.identical else "❌"
        service = comp.service_a if comp.service_a == comp.service_b else (
            f"{comp.service_a} / {comp.service_b}"
        )
        print(f"\n  {status} 命令 #{comp.index}: {service}")

        if comp.identical:
            print("      → 完全一致")
        else:
            for diff in comp.diffs:
                print(f"      差异字段: {diff.field_name}")
                print(f"        文件 A: {_truncate(diff.file_a_value, 200)}")
                print(f"        文件 B: {_truncate(diff.file_b_value, 200)}")

    # 额外命令
    if compare.only_in_a:
        print(f"\n  --- 仅在文件 A 中的命令 ---")
        for cmd in compare.only_in_a:
            print(f"  [{cmd.index}] {cmd.service}")

    if compare.only_in_b:
        print(f"\n  --- 仅在文件 B 中的命令 ---")
        for cmd in compare.only_in_b:
            print(f"  [{cmd.index}] {cmd.service}")

    # 总结
    print(f"\n{'=' * 80}")
    print("总结")
    print(f"{'=' * 80}")
    if diff_count == 0 and not compare.only_in_a and not compare.only_in_b:
        print("  两次执行的命令序列完全一致，无任何差异。")
    else:
        print(f"  两次执行发现 {diff_count} 处差异：")
        for comp in compare.comparisons:
            if not comp.identical:
                for diff in comp.diffs:
                    if diff.field_name == "response_summary":
                        print(
                            f"    - 命令 #{comp.index} ({comp.service_a}): "
                            f"响应内容不同"
                        )
                    elif diff.field_name == "duration":
                        print(
                            f"    - 命令 #{comp.index} ({comp.service_a}): "
                            f"执行时间不同 "
                            f"({diff.file_a_value} vs {diff.file_b_value})"
                        )
                    else:
                        print(
                            f"    - 命令 #{comp.index}: "
                            f"{diff.field_name} 不同"
                        )
    print()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI 入口。"""
    import io

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if len(sys.argv) < 3:
        print(
            "Usage: python -m pcapng_tools.compare_pcapng "
            "<file_a.pcapng> <file_b.pcapng> [output.txt]"
        )
        sys.exit(1)

    file_a = Path(sys.argv[1])
    file_b = Path(sys.argv[2])
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    if not file_a.is_file():
        print(f"错误: 文件不存在 — {file_a}")
        sys.exit(1)
    if not file_b.is_file():
        print(f"错误: 文件不存在 — {file_b}")
        sys.exit(1)

    # 解析两个文件
    result_a = parse_pcapng(file_a)
    result_b = parse_pcapng(file_b)

    # 如果指定了输出文件，重定向 stdout
    if output_path is not None:
        original_stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(
            open(output_path, "wb"),  # noqa: SIM115
            encoding="utf-8",
        )

    try:
        # 打印各自的解析结果
        print_parse_result(result_a)
        print_parse_result(result_b)

        # 对比并输出
        compare = compare_results(result_a, result_b)
        print_compare_result(compare)
    finally:
        if output_path is not None:
            sys.stdout.close()
            sys.stdout = original_stdout
            print(f"结果已写入: {output_path}")


if __name__ == "__main__":
    main()
