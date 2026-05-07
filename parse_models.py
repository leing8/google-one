"""解析结果数据模型。

pcapng / ADB 协议解析的不可变数据容器。
所有模型遵循 Python 最佳实践使用冻结数据类 + 完整类型注解。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique


# ── 枚举 ───────────────────────────────────────────────────────────


@unique
class Direction(Enum):
    """USB 传输方向。"""

    OUT = 0  # Host → Device
    IN = 1   # Device → Host


@unique
class AdbCommand(Enum):
    """ADB 协议命令类型。"""

    CNXN = "CNXN"
    OPEN = "OPEN"
    OKAY = "OKAY"
    WRTE = "WRTE"
    CLSE = "CLSE"
    AUTH = "AUTH"


@unique
class CommandType(Enum):
    """高层命令分类。"""

    REBOOT = "reboot"
    SHELL = "shell"
    SHELL_V2 = "shell_v2"
    PUSH = "push"
    PULL = "pull"
    CONNECT = "connect"


# ── USB 层 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UsbBulkTransfer:
    """单个 USB bulk transfer 帧。

    属性:
        frame_number: pcapng 帧编号（1-based）。
        direction: 传输方向。
        payload: 实际捕获的数据载荷（可能被 snaplen 截断）。
        usb_data_length: USBPcap 头中声明的完整数据长度。
    """

    frame_number: int
    direction: Direction
    payload: bytes
    usb_data_length: int


# ── ADB 协议层 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdbMessage:
    """单个 ADB 协议消息。

    ADB 消息格式：24 字节头 + 可变长度数据。
    头部: command(4) + arg0(4) + arg1(4) + data_length(4) + crc(4) + magic(4)

    属性:
        command: ADB 命令类型。
        arg0: 参数 0（通常为 local_id）。
        arg1: 参数 1（通常为 remote_id）。
        data_length: 声明的数据长度。
        payload: 实际数据载荷。
        frame_number: 来源 USB 帧编号。
        direction: 传输方向。
    """

    command: AdbCommand
    arg0: int
    arg1: int
    data_length: int
    payload: bytes
    frame_number: int
    direction: Direction


# ── ADB Stream 层 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncFileTransfer:
    """ADB sync 协议文件传输信息。

    属性:
        remote_path: 设备端文件路径。
        file_data: 重组后的完整文件数据。
        file_size: 文件大小（字节）。
    """

    remote_path: str
    file_data: bytes
    file_size: int


@dataclass(frozen=True)
class AdbStream:
    """一个完整的 ADB 通信流（OPEN → WRTE... → CLSE）。

    属性:
        local_id: 本地 stream ID。
        remote_id: 远端 stream ID。
        destination: stream 目标（如 "shell:twrp --version"）。
        messages: 该 stream 内所有 ADB 消息（按时序）。
    """

    local_id: int
    remote_id: int
    destination: str
    messages: tuple[AdbMessage, ...]


# ── 高层解析结果 ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedCommand:
    """一个完整的已解析命令及其结果。

    属性:
        step: 命令序号（1-based）。
        command_type: 命令分类。
        command: 完整命令字符串。
        output: 命令输出文本。
        file_transfer: 如有文件传输则包含详情，否则为 None。
        stream: 原始 ADB stream。
    """

    step: int
    command_type: CommandType
    command: str
    output: str
    file_transfer: SyncFileTransfer | None
    stream: AdbStream


@dataclass(frozen=True)
class ConnectionInfo:
    """ADB 连接信息。

    属性:
        host_features: 主机端支持的特性列表。
        device_banner: 设备端 banner 字符串。
        device_features: 设备端支持的特性列表。
    """

    host_features: tuple[str, ...]
    device_banner: str
    device_features: tuple[str, ...]


@dataclass(frozen=True)
class ParseResult:
    """完整的 pcapng 解析结果。

    属性:
        source_file: 源 pcapng 文件路径。
        total_usb_frames: USB bulk transfer 帧总数。
        total_adb_messages: ADB 消息总数。
        connection: ADB 连接信息。
        commands: 按时序排列的已解析命令列表。
    """

    source_file: str
    total_usb_frames: int
    total_adb_messages: int
    connection: ConnectionInfo
    commands: tuple[ParsedCommand, ...]
