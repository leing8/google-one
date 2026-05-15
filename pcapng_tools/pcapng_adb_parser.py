"""
pcapng ADB 命令解析器 — 从 USBPcap 抓包文件提取完整 ADB 命令序列。

使用 tshark 逐帧解析 pcapng 文件，解码 USB BULK 传输中的 ADB 协议。
不依赖已知命令池，从原始帧数据中重建完整命令。

ADB 协议结构：
    每条 ADB 消息由 24 字节头 + 可变长度载荷组成。
    头部结构：[CMD:4][ARG0:4][ARG1:4][LEN:4][CRC:4][MAGIC:4]
    CMD 类型：CNXN, OPEN, OKAY, WRTE, CLSE

    关键特性：
    - OPEN 消息的服务名（payload）通常在独立的后续帧中发送
    - WRTE 消息的数据载荷也在独立帧中
    - ADB v2 shell 协议使用额外的 shell protocol header

用法：
    python -m michanger.common.pcapng_adb_parser <pcapng_file>
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TSHARK_PATH = Path(r"C:\Program Files\Wireshark\tshark.exe")

_CREATION_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
)

# ADB 消息类型常量
_ADB_CMD_CNXN = b"CNXN"
_ADB_CMD_OPEN = b"OPEN"
_ADB_CMD_OKAY = b"OKAY"
_ADB_CMD_WRTE = b"WRTE"
_ADB_CMD_CLSE = b"CLSE"

# ADB 消息头长度
_ADB_HEADER_LEN = 24


@dataclass
class ParsedFrame:
    """从 tshark 输出解析的单个 USB 帧。"""
    frame_number: int
    timestamp: float
    src: str
    dst: str
    endpoint: int
    data_len: int
    raw_data: bytes


@dataclass
class AdbMessage:
    """ADB 消息"""
    frame_no: int
    timestamp: float
    direction: str
    command: str
    arg0: int
    arg1: int
    data_length: int
    payload: bytes


@dataclass
class AdbCommand:
    """一条完整的 ADB 命令及其响应。"""
    index: int                      # 命令序号
    service: str                    # 服务名（shell,v2,raw:xxx / sync: / reboot: 等）
    local_id: int = 0
    remote_id: int = 0
    open_frame: int = 0
    open_time: float = 0.0
    responses: list[str] = field(default_factory=list)
    response_frames: list[int] = field(default_factory=list)
    close_frame: int = 0
    close_time: float = 0.0


@dataclass
class ExtractedCommand:
    """供对比工具使用的高级抽象命令模型。"""
    index: int
    service: str
    command_type: str
    command_detail: str
    response_summary: str
    start_time: float
    end_time: float


@dataclass
class ParseResult:
    """完整的解析结果，供对比工具使用。"""
    file_path: str
    total_frames: int
    adb_messages: list[AdbMessage]
    sessions: list
    commands: list[ExtractedCommand]
    connection_info: str = ""


def _hex_to_bytes(hex_str: str) -> bytes:
    """将 tshark 输出的十六进制字符串转换为 bytes。"""
    cleaned = hex_str.replace(":", "").replace(" ", "")
    if not cleaned:
        return b""
    return bytes.fromhex(cleaned)


def _safe_decode(data: bytes) -> str:
    """安全解码 bytes 为字符串，去除尾部 null。"""
    return data.decode("utf-8", errors="replace").rstrip("\x00")


def _extract_frames(pcapng_path: Path) -> list[ParsedFrame]:
    """使用 tshark 从 pcapng 提取所有 USB 帧。"""
    cmd = [
        str(_TSHARK_PATH),
        "-r", str(pcapng_path),
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "usb.src",
        "-e", "usb.dst",
        "-e", "usb.endpoint_address",
        "-e", "usb.data_len",
        "-e", "usb.capdata",
        "-E", "separator=|",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=_CREATION_FLAGS,
    )

    frames: list[ParsedFrame] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 6:
            continue

        frame_num = int(parts[0]) if parts[0] else 0
        time_rel = float(parts[1]) if parts[1] else 0.0
        src = parts[2]
        dst = parts[3]
        endpoint = int(parts[4], 16) if parts[4] else 0
        data_len = int(parts[5]) if parts[5] else 0
        raw_data = _hex_to_bytes(parts[6]) if len(parts) > 6 and parts[6] else b""

        frames.append(ParsedFrame(
            frame_number=frame_num,
            timestamp=time_rel,
            src=src,
            dst=dst,
            endpoint=endpoint,
            data_len=data_len,
            raw_data=raw_data,
        ))

    return frames


def parse_pcapng(pcapng_path: Path) -> ParseResult:
    """解析 pcapng 文件中的所有 ADB 命令并返回对比工具所需的结构。"""
    frames = _extract_frames(pcapng_path)

    commands: list[AdbCommand] = []
    adb_messages: list[AdbMessage] = []
    cmd_index = 0

    # local_id -> AdbCommand 映射
    channels: dict[int, AdbCommand] = {}

    # 状态机：记录上一个 OPEN/WRTE 头帧，等待后续载荷帧
    pending_open_local_id: int | None = None
    pending_wrte_info: tuple[int, int, str] | None = None  # (local_id, remote_id, src)

    i = 0
    while i < len(frames):
        frame = frames[i]

        # 只处理有数据的 BULK 帧 (endpoint 0x01 OUT 或 0x81 IN)
        if not frame.raw_data:
            i += 1
            continue

        data = frame.raw_data

        # 检查是否为 ADB 消息头（24 bytes, 前4字节为命令类型）
        if len(data) >= _ADB_HEADER_LEN and data[:4] in (
            _ADB_CMD_CNXN, _ADB_CMD_OPEN, _ADB_CMD_OKAY,
            _ADB_CMD_WRTE, _ADB_CMD_CLSE,
        ):
            msg_type = data[:4]
            arg0 = int.from_bytes(data[4:8], "little")
            arg1 = int.from_bytes(data[8:12], "little")
            payload_len = int.from_bytes(data[12:16], "little")

            if msg_type == _ADB_CMD_CNXN:
                # 连接握手 — 记录但不作为命令
                adb_messages.append(AdbMessage(
                    frame_no=frame.frame_number, timestamp=frame.timestamp,
                    direction="host->device" if frame.endpoint == 1 else "device->host",
                    command="CNXN", arg0=arg0, arg1=arg1, data_length=payload_len, payload=b""
                ))

            elif msg_type == _ADB_CMD_OPEN:
                # OPEN: arg0=local_id, payload=service_name
                # 载荷在下一个数据帧中
                pending_open_local_id = arg0
                adb_messages.append(AdbMessage(
                    frame_no=frame.frame_number, timestamp=frame.timestamp,
                    direction="host->device" if frame.endpoint == 1 else "device->host",
                    command="OPEN", arg0=arg0, arg1=arg1, data_length=payload_len, payload=b""
                ))

            elif msg_type == _ADB_CMD_OKAY:
                # OKAY: arg0=local_id, arg1=remote_id
                if arg1 in channels:
                    channels[arg1].remote_id = arg0
                adb_messages.append(AdbMessage(
                    frame_no=frame.frame_number, timestamp=frame.timestamp,
                    direction="host->device" if frame.endpoint == 1 else "device->host",
                    command="OKAY", arg0=arg0, arg1=arg1, data_length=payload_len, payload=b""
                ))

            elif msg_type == _ADB_CMD_WRTE:
                # WRTE: arg0=local_id, arg1=remote_id
                # 载荷在下一个数据帧中
                pending_wrte_info = (arg0, arg1, frame.src)
                adb_messages.append(AdbMessage(
                    frame_no=frame.frame_number, timestamp=frame.timestamp,
                    direction="host->device" if frame.endpoint == 1 else "device->host",
                    command="WRTE", arg0=arg0, arg1=arg1, data_length=payload_len, payload=b""
                ))

            elif msg_type == _ADB_CMD_CLSE:
                # CLSE: 关闭通道
                if arg1 in channels:
                    channels[arg1].close_frame = frame.frame_number
                    channels[arg1].close_time = frame.timestamp
                adb_messages.append(AdbMessage(
                    frame_no=frame.frame_number, timestamp=frame.timestamp,
                    direction="host->device" if frame.endpoint == 1 else "device->host",
                    command="CLSE", arg0=arg0, arg1=arg1, data_length=payload_len, payload=b""
                ))

        elif pending_open_local_id is not None:
            # 这是 OPEN 命令的服务名载荷
            service = _safe_decode(data)
            cmd_index += 1
            cmd_obj = AdbCommand(
                index=cmd_index,
                service=service,
                local_id=pending_open_local_id,
                open_frame=frame.frame_number,
                open_time=frame.timestamp,
            )
            channels[pending_open_local_id] = cmd_obj
            commands.append(cmd_obj)
            pending_open_local_id = None

        elif pending_wrte_info is not None:
            # 这是 WRTE 命令的数据载荷
            wr_local_id, wr_remote_id, wr_src = pending_wrte_info

            # 查找对应通道
            target = channels.get(wr_remote_id) or channels.get(wr_local_id)

            if target:
                # ADB v2 shell protocol: 第一个字节是 packet type
                # 0x00=STDIN, 0x01=STDOUT, 0x02=STDERR, 0x03=EXIT
                if "shell,v2" in target.service:
                    if len(data) >= 5:
                        pkt_type = data[0]
                        # 4 bytes length (little-endian) at data[1:5]
                        shell_payload = data[5:]
                        decoded = _safe_decode(shell_payload)
                        if pkt_type == 0x01:  # STDOUT
                            target.responses.append(decoded)
                            target.response_frames.append(frame.frame_number)
                        elif pkt_type == 0x03:  # EXIT
                            exit_code = int.from_bytes(data[5:6], "little") if len(data) > 5 else -1
                            target.responses.append(f"[EXIT:{exit_code}]")
                            target.response_frames.append(frame.frame_number)
                        elif pkt_type == 0x00:  # STDIN (host→device)
                            # 这是 shell 命令的 stdin 输入
                            if decoded:
                                target.responses.append(f"[STDIN:{decoded}]")
                                target.response_frames.append(frame.frame_number)
                    elif len(data) >= 1:
                        pkt_type = data[0]
                        if pkt_type == 0x03:
                            target.responses.append("[EXIT:0]")
                            target.response_frames.append(frame.frame_number)
                else:
                    # 非 shell 协议（sync, reboot 等）
                    decoded = _safe_decode(data)
                    if decoded:
                        target.responses.append(decoded)
                        target.response_frames.append(frame.frame_number)

            pending_wrte_info = None

            # Attach payload to the last WRTE message if possible
            if adb_messages and adb_messages[-1].command == "WRTE":
                adb_messages[-1].payload = data

        i += 1

    # Convert AdbCommand list to ExtractedCommand list
    extracted_commands = []
    for cmd in commands:
        if cmd.service.startswith("shell:"):
            ctype = "shell"
            cdetail = cmd.service[6:]
        elif cmd.service.startswith("shell,v2:"):
            ctype = "shell"
            cdetail = cmd.service[9:]
        elif cmd.service.startswith("sync:"):
            ctype = "sync"
            cdetail = "sync"
        else:
            parts = cmd.service.split(":", 1)
            ctype = parts[0]
            cdetail = parts[1] if len(parts) > 1 else cmd.service

        resp_summary = "\n".join(cmd.responses)

        end_time = cmd.close_time
        if end_time == 0.0 and cmd.response_frames:
            # fallback to time of last response
            # we don't have individual response timestamps without searching, so use open_time
            end_time = cmd.open_time

        extracted_commands.append(ExtractedCommand(
            index=cmd.index,
            service=cmd.service,
            command_type=ctype,
            command_detail=cdetail,
            response_summary=resp_summary,
            start_time=cmd.open_time,
            end_time=end_time,
        ))

    return ParseResult(
        file_path=str(pcapng_path),
        total_frames=len(frames),
        adb_messages=adb_messages,
        sessions=[],
        commands=extracted_commands,
        connection_info=f"Total Extracted: {len(extracted_commands)}"
    )


def print_commands(result: ParseResult) -> None:
    """格式化打印解析出的命令序列。"""
    commands = result.commands
    print(f"\n{'='*80}")
    print(f"Total ADB commands: {len(commands)}")
    print(f"{'='*80}\n")

    for cmd in commands:
        print(f"[Step {cmd.index}] Time {cmd.start_time:.3f}s")
        print(f"  Service:   {cmd.service}")

        if cmd.response_summary:
            display = cmd.response_summary
            if len(display) > 300:
                display = display[:300] + f"... ({len(cmd.response_summary)} chars total)"
            print(f"  Response:  {display!r}")

        print()


def main() -> None:
    """CLI 入口。"""
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <pcapng_file>", file=sys.stderr)
        sys.exit(1)

    pcapng_path = Path(sys.argv[1])
    if not pcapng_path.is_file():
        print(f"File not found: {pcapng_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing: {pcapng_path}")
    result = parse_pcapng(pcapng_path)
    print_commands(result)


if __name__ == "__main__":
    main()
