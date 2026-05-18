"""
Change Location Only — 数据模型。

所有模型均使用 frozen=True 保证不可变性（PEP 557）。

参考：
- https://docs.python.org/3/library/dataclasses.html
- 15.0/15.1 pcapng 双份抓包对比分析
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PhaseResult:
    """单阶段执行结果。

    Attributes:
        phase_name: 阶段名称
        phase_number: 阶段编号（1-8）
        success: 是否成功
        message: 结果描述
        commands_executed: 执行的命令数量
    """

    phase_name: str
    phase_number: int
    success: bool
    message: str
    commands_executed: int = 0


@dataclass(frozen=True)
class ChangeLocationResult:
    """完整 Change Location Only 执行结果。

    Attributes:
        serial: 设备序列号
        phase_results: 各阶段的执行结果（不可变元组）
        mi_dir_path: 探测到的 mi 目录路径
        third_party_packages: 第三方应用包名列表
        pm_clear_output: Step 1 pm clear 的输出（可能 "Failed"）
        success: 整体是否成功
    """

    serial: str
    phase_results: tuple[PhaseResult, ...] = field(default_factory=tuple)
    mi_dir_path: str = ""
    third_party_packages: tuple[str, ...] = field(default_factory=tuple)
    pm_clear_output: str = ""
    success: bool = False

    @property
    def total_phases(self) -> int:
        """总阶段数。"""
        return len(self.phase_results)

    @property
    def success_count(self) -> int:
        """成功阶段数。"""
        return sum(1 for r in self.phase_results if r.success)

    @property
    def total_commands(self) -> int:
        """执行的总命令数。"""
        return sum(r.commands_executed for r in self.phase_results)
