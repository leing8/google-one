"""
使用序列对齐算法（LCS/SequenceMatcher）对比两个 pcapng 文件的 ADB 命令。

核心改进：
1. 将每条命令的 service 泛化为"命令模板"（去掉随机值），用于序列对齐
2. 用 difflib.SequenceMatcher 做最长公共子序列匹配，找出真正的
   插入/删除/修改，避免位置偏移造成的级联假差异
3. 对齐后的匹配对再做逐字段精细对比，区分"结构不同"和"仅随机值不同"
"""

from __future__ import annotations

import io
import logging
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .pcapng_adb_parser import (
    ExtractedCommand,
    ParseResult,
    parse_pcapng,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 命令模板化 — 去掉随机值，保留命令结构
# ---------------------------------------------------------------------------

# sed 命令的模板化：保留属性名，去掉具体值
_SED_PATTERN = re.compile(
    r"sed -i 's\|([^=]+)=([^|]*)\|([^=]+)=([^|]*)\|g' (.+)"
)

# service call alarm 的时区参数
_ALARM_PATTERN = re.compile(r"service call alarm 3 s16 (.+)")

# rm -rf 后面跟随机路径的模式
_RM_APP_PATTERN = re.compile(r"rm -rf /data/app/~~[^/]+/([^/]+)-[^/]+/\*")

# 文件 push 的 SND2 路径
_SYNC_PATTERN = re.compile(r"SEND (.+)")


def _normalize_command(cmd: ExtractedCommand) -> str:
    """将命令泛化为模板字符串，用于序列对齐。

    目标：相同逻辑操作但不同随机值的命令 → 相同模板
    """
    detail = cmd.command_detail

    # sed 替换命令 → 只保留属性名和目标文件
    m = _SED_PATTERN.match(detail)
    if m:
        prop_name = m.group(1)
        target_file = m.group(5)
        return f"sed:{prop_name}@{target_file}"

    # service call alarm → 统一为模板
    m = _ALARM_PATTERN.match(detail)
    if m:
        return "service_call_alarm:timezone"

    # rm -rf /data/app/~~xxx/pkg-xxx/* → 保留包名
    m = _RM_APP_PATTERN.match(detail)
    if m:
        return f"rm_app:{m.group(1)}"

    # sync → file_transfer 不区分
    if cmd.command_type == "sync":
        return "sync:file_transfer"

    # pm clear XXX → 保留包名
    if detail.startswith("pm clear "):
        return f"pm_clear:{detail[9:]}"

    # 其他命令直接用 service 做模板
    return cmd.service


# ---------------------------------------------------------------------------
# 对齐结果模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlignedPair:
    """一对已对齐的命令。"""

    cmd_a: ExtractedCommand | None  # None = 仅在 B 中
    cmd_b: ExtractedCommand | None  # None = 仅在 A 中
    template: str
    status: str  # "identical" / "value_diff" / "only_a" / "only_b"
    diff_fields: tuple[tuple[str, str, str], ...] = ()  # (field, val_a, val_b)


@dataclass
class AlignedCompareResult:
    """对齐后的完整对比结果。"""

    file_a: str
    file_b: str
    total_a: int
    total_b: int
    pairs: list[AlignedPair] = field(default_factory=list)

    @property
    def identical_count(self) -> int:
        return sum(1 for p in self.pairs if p.status == "identical")

    @property
    def value_diff_count(self) -> int:
        return sum(1 for p in self.pairs if p.status == "value_diff")

    @property
    def only_a_count(self) -> int:
        return sum(1 for p in self.pairs if p.status == "only_a")

    @property
    def only_b_count(self) -> int:
        return sum(1 for p in self.pairs if p.status == "only_b")


# ---------------------------------------------------------------------------
# 序列对齐 + 精细对比
# ---------------------------------------------------------------------------

def _compare_fields(
    cmd_a: ExtractedCommand,
    cmd_b: ExtractedCommand,
) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    """对齐后对比两条命令的具体字段差异。"""
    diffs: list[tuple[str, str, str]] = []

    if cmd_a.service != cmd_b.service:
        diffs.append(("service", cmd_a.service, cmd_b.service))

    if cmd_a.command_detail != cmd_b.command_detail:
        diffs.append(("command_detail", cmd_a.command_detail, cmd_b.command_detail))

    if cmd_a.response_summary != cmd_b.response_summary:
        diffs.append((
            "response",
            cmd_a.response_summary[:200],
            cmd_b.response_summary[:200],
        ))

    status = "identical" if len(diffs) == 0 else "value_diff"
    return status, tuple(diffs)


def aligned_compare(
    result_a: ParseResult,
    result_b: ParseResult,
) -> AlignedCompareResult:
    """使用序列对齐算法对比两个解析结果。"""
    cmds_a = result_a.commands
    cmds_b = result_b.commands

    # 1. 生成模板序列
    templates_a = [_normalize_command(c) for c in cmds_a]
    templates_b = [_normalize_command(c) for c in cmds_b]

    # 2. 用 SequenceMatcher 做对齐
    matcher = SequenceMatcher(None, templates_a, templates_b)
    pairs: list[AlignedPair] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # 模板匹配 — 逐对精细比较
            for i, j in zip(range(i1, i2), range(j1, j2)):
                status, diffs = _compare_fields(cmds_a[i], cmds_b[j])
                pairs.append(AlignedPair(
                    cmd_a=cmds_a[i],
                    cmd_b=cmds_b[j],
                    template=templates_a[i],
                    status=status,
                    diff_fields=diffs,
                ))

        elif tag == "replace":
            # 模板不同 — 先尝试内部对齐
            sub_a = list(range(i1, i2))
            sub_b = list(range(j1, j2))
            # 简单处理：按顺序配对，多余的标记为 only
            k = 0
            while k < len(sub_a) and k < len(sub_b):
                i_idx = sub_a[k]
                j_idx = sub_b[k]
                status, diffs = _compare_fields(
                    cmds_a[i_idx], cmds_b[j_idx]
                )
                pairs.append(AlignedPair(
                    cmd_a=cmds_a[i_idx],
                    cmd_b=cmds_b[j_idx],
                    template=f"{templates_a[i_idx]} ↔ {templates_b[j_idx]}",
                    status=status,
                    diff_fields=diffs,
                ))
                k += 1
            for remaining in sub_a[k:]:
                pairs.append(AlignedPair(
                    cmd_a=cmds_a[remaining],
                    cmd_b=None,
                    template=templates_a[remaining],
                    status="only_a",
                ))
            for remaining in sub_b[k:]:
                pairs.append(AlignedPair(
                    cmd_a=None,
                    cmd_b=cmds_b[remaining],
                    template=templates_b[remaining],
                    status="only_b",
                ))

        elif tag == "delete":
            # 仅在 A 中
            for i in range(i1, i2):
                pairs.append(AlignedPair(
                    cmd_a=cmds_a[i],
                    cmd_b=None,
                    template=templates_a[i],
                    status="only_a",
                ))

        elif tag == "insert":
            # 仅在 B 中
            for j in range(j1, j2):
                pairs.append(AlignedPair(
                    cmd_a=None,
                    cmd_b=cmds_b[j],
                    template=templates_b[j],
                    status="only_b",
                ))

    return AlignedCompareResult(
        file_a=result_a.file_path,
        file_b=result_b.file_path,
        total_a=len(cmds_a),
        total_b=len(cmds_b),
        pairs=pairs,
    )


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 120) -> str:
    """截断文本。"""
    text = text.replace("\n", " | ")
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def print_aligned_result(result: AlignedCompareResult) -> None:
    """打印对齐后的对比结果。"""
    print(f"\n{'=' * 100}")
    print("对齐对比结果（使用序列对齐算法）")
    print(f"{'=' * 100}")
    print(f"  文件 A: {Path(result.file_a).name}  ({result.total_a} 条命令)")
    print(f"  文件 B: {Path(result.file_b).name}  ({result.total_b} 条命令)")
    print()
    print(f"  ✅ 完全相同:     {result.identical_count}")
    print(f"  🔄 仅值不同:     {result.value_diff_count}")
    print(f"  ➕ 仅在 A 中:    {result.only_a_count}")
    print(f"  ➕ 仅在 B 中:    {result.only_b_count}")
    print()

    # ---------------------------------------------------------------
    # 1. 仅在 A 或 B 中的命令（真正的结构差异）
    # ---------------------------------------------------------------
    only_a = [p for p in result.pairs if p.status == "only_a"]
    only_b = [p for p in result.pairs if p.status == "only_b"]

    if only_a or only_b:
        print(f"\n{'─' * 100}")
        print("📌 真正的结构差异（命令插入/删除）")
        print(f"{'─' * 100}")

        if only_a:
            print(f"\n  ➕ 仅在文件 A 中的命令 ({len(only_a)} 条):")
            for p in only_a:
                assert p.cmd_a is not None
                print(
                    f"    A[{p.cmd_a.index:3d}] "
                    f"[{p.cmd_a.command_type:10s}] "
                    f"{_truncate(p.cmd_a.command_detail, 90)}"
                )

        if only_b:
            print(f"\n  ➕ 仅在文件 B 中的命令 ({len(only_b)} 条):")
            for p in only_b:
                assert p.cmd_b is not None
                print(
                    f"    B[{p.cmd_b.index:3d}] "
                    f"[{p.cmd_b.command_type:10s}] "
                    f"{_truncate(p.cmd_b.command_detail, 90)}"
                )
    else:
        print("\n  📌 无结构差异 — 两次执行的命令序列完全对齐")

    # ---------------------------------------------------------------
    # 2. 值不同的命令
    # ---------------------------------------------------------------
    value_diffs = [p for p in result.pairs if p.status == "value_diff"]

    if value_diffs:
        print(f"\n{'─' * 100}")
        print(f"🔄 值不同的命令 ({len(value_diffs)} 条)")
        print(f"{'─' * 100}")

        # 按差异类型分组
        randomized: list[AlignedPair] = []
        response_only: list[AlignedPair] = []
        other_diff: list[AlignedPair] = []

        for p in value_diffs:
            diff_field_names = {d[0] for d in p.diff_fields}
            # 仅 command_detail 不同 → 随机化参数
            if diff_field_names == {"command_detail"} or diff_field_names == {"service", "command_detail"}:
                randomized.append(p)
            elif diff_field_names == {"response"} or diff_field_names == {"command_detail", "response"} or diff_field_names == {"service", "command_detail", "response"}:
                # 命令不同且响应不同
                if "command_detail" in diff_field_names:
                    randomized.append(p)
                else:
                    response_only.append(p)
            else:
                other_diff.append(p)

        if randomized:
            print(f"\n  --- 随机化参数不同（{len(randomized)} 条） ---")
            print("  （命令结构相同，但随机生成的值不同 — 预期行为）")
            # 只显示前 10 条示例
            shown = min(10, len(randomized))
            for p in randomized[:shown]:
                assert p.cmd_a is not None and p.cmd_b is not None
                print(f"\n    模板: {_truncate(p.template, 70)}")
                for fname, va, vb in p.diff_fields:
                    if fname == "command_detail":
                        print(f"      A: {_truncate(va, 90)}")
                        print(f"      B: {_truncate(vb, 90)}")
            if len(randomized) > shown:
                print(f"\n    ... 还有 {len(randomized) - shown} 条类似差异")

        if response_only:
            print(f"\n  --- 仅响应不同（{len(response_only)} 条） ---")
            for p in response_only[:10]:
                assert p.cmd_a is not None and p.cmd_b is not None
                print(
                    f"\n    命令: {_truncate(p.cmd_a.command_detail, 80)}"
                )
                for fname, va, vb in p.diff_fields:
                    if fname == "response":
                        print(f"      A 响应: {_truncate(va, 80)}")
                        print(f"      B 响应: {_truncate(vb, 80)}")

        if other_diff:
            print(f"\n  --- 其他差异（{len(other_diff)} 条） ---")
            for p in other_diff:
                assert p.cmd_a is not None and p.cmd_b is not None
                print(f"\n    A[{p.cmd_a.index}]: {_truncate(p.cmd_a.service, 80)}")
                print(f"    B[{p.cmd_b.index}]: {_truncate(p.cmd_b.service, 80)}")
                for fname, va, vb in p.diff_fields:
                    print(f"      {fname}:")
                    print(f"        A: {_truncate(va, 80)}")
                    print(f"        B: {_truncate(vb, 80)}")

    # ---------------------------------------------------------------
    # 3. 完全一致的命令列表
    # ---------------------------------------------------------------
    identical = [p for p in result.pairs if p.status == "identical"]
    if identical:
        print(f"\n{'─' * 100}")
        print(f"✅ 完全一致的命令 ({len(identical)} 条)")
        print(f"{'─' * 100}")
        for p in identical:
            assert p.cmd_a is not None
            print(
                f"    [{p.cmd_a.index:3d}] "
                f"[{p.cmd_a.command_type:10s}] "
                f"{_truncate(p.cmd_a.command_detail, 80)}"
            )

    # ---------------------------------------------------------------
    # 最终总结
    # ---------------------------------------------------------------
    print(f"\n{'=' * 100}")
    print("最终总结")
    print(f"{'=' * 100}")

    if result.only_a_count == 0 and result.only_b_count == 0:
        print("  两次执行的命令序列 结构完全一致（无插入/删除）。")
    else:
        print(
            f"  结构差异: 文件 A 多 {result.only_a_count} 条, "
            f"文件 B 多 {result.only_b_count} 条"
        )

    print(f"  完全相同: {result.identical_count} 条")
    print(f"  仅值不同: {result.value_diff_count} 条（随机化参数差异）")
    total_aligned = result.identical_count + result.value_diff_count
    total_all = total_aligned + result.only_a_count + result.only_b_count
    if total_all > 0:
        pct = total_aligned / total_all * 100
        print(f"  对齐率:   {total_aligned}/{total_all} ({pct:.1f}%)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if len(sys.argv) < 3:
        print(
            "Usage: python -m pcapng_tools.compare_pcapng_aligned "
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

    # 解析
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
        # 对齐对比
        compare = aligned_compare(result_a, result_b)
        print_aligned_result(compare)
    finally:
        if output_path is not None:
            sys.stdout.close()
            sys.stdout = original_stdout
            print(f"结果已写入: {output_path}")


if __name__ == "__main__":
    main()
