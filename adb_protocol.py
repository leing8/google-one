"""ADB 协议解析器。

从 USB bulk transfer 载荷中解析 ADB 协议消息，
将消息重组为逻辑 stream，并提取高层命令。

ADB 协议参考:
    https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/protocol.txt

ADB 消息格式（24 字节头 + 数据）:
    command:     uint32  (e.g. 'CNXN', 'OPEN', 'WRTE', 'CLSE', 'OKAY', 'AUTH')
    arg0:        uint32
    arg1:        uint32
    data_length: uint32
    data_crc32:  uint32
    magic:       uint32  (command ^ 0xFFFFFFFF)
    [data]:      data_length bytes (可能在下一个 USB 帧中)

ADB Sync 子协议（用于文件推送/拉取）:
    STA2/STAT:   stat 查询
    SND2/SEND:   发送文件
    DATA:        数据块
    DONE:        传输完成
    OKAY:        确认
    QUIT:        退出 sync 模式
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from parse_models import (
    AdbCommand,
    AdbMessage,
    AdbStream,
    CommandType,
    ConnectionInfo,
    Direction,
    ParsedCommand,
    ParseResult,
    SyncFileTransfer,
    UsbBulkTransfer,
)
from pcapng_parser import parse_pcapng_file

logger = logging.getLogger(__name__)

# ── ADB 命令魔数映射 ──────────────────────────────────────────────

_ADB_CMD_MAP: dict[int, AdbCommand] = {}
for _cmd in AdbCommand:
    _val = struct.unpack("<I", _cmd.value.encode("ascii"))[0]
    _ADB_CMD_MAP[_val] = _cmd


# ── ADB 消息解析 ──────────────────────────────────────────────────


def _try_parse_adb_header(payload: bytes) -> AdbMessage | None:
    """尝试从载荷中解析 ADB 消息头。

    ADB 消息头 = 24 字节：
        command(4) + arg0(4) + arg1(4) + data_length(4) + crc(4) + magic(4)

    验证: magic == command ^ 0xFFFFFFFF

    参数:
        payload: USB bulk transfer 载荷。

    返回:
        解析成功返回 AdbMessage（payload 为空，等待后续帧填充），
        否则返回 None。
    """
    if len(payload) < 24:
        return None

    cmd_raw, arg0, arg1, data_len, crc, magic = struct.unpack_from(
        "<IIIIII", payload, 0
    )

    # 验证 magic
    expected_magic = cmd_raw ^ 0xFFFFFFFF
    if magic != expected_magic:
        return None

    # 验证命令类型
    cmd = _ADB_CMD_MAP.get(cmd_raw)
    if cmd is None:
        return None

    # 数据紧随头部（同一帧）或在后续帧中
    inline_data = payload[24:] if len(payload) > 24 else b""

    return AdbMessage(
        command=cmd,
        arg0=arg0,
        arg1=arg1,
        data_length=data_len,
        payload=inline_data,
        frame_number=0,  # 由调用方设置
        direction=Direction.OUT,  # 由调用方设置
    )


def parse_adb_messages(
    transfers: list[UsbBulkTransfer],
) -> list[AdbMessage]:
    """从 USB bulk transfer 序列中解析所有 ADB 消息。

    处理 ADB 消息头和数据载荷分帧的情况：
    - 头部帧：包含 24 字节 ADB 头（可能包含内联数据）
    - 数据帧：紧随头部帧，包含剩余数据

    参数:
        transfers: USB bulk transfer 帧列表。

    返回:
        按时序排列的 ADB 消息列表。
    """
    messages: list[AdbMessage] = []
    pending_msg: AdbMessage | None = None
    pending_data = bytearray()

    for transfer in transfers:
        payload = transfer.payload

        # 尝试解析为 ADB 头
        header = _try_parse_adb_header(payload)

        if header is not None:
            # 如果有待处理的消息，先完成它
            if pending_msg is not None:
                completed = AdbMessage(
                    command=pending_msg.command,
                    arg0=pending_msg.arg0,
                    arg1=pending_msg.arg1,
                    data_length=pending_msg.data_length,
                    payload=bytes(pending_data),
                    frame_number=pending_msg.frame_number,
                    direction=pending_msg.direction,
                )
                messages.append(completed)
                pending_msg = None
                pending_data.clear()

            # 新消息
            msg = AdbMessage(
                command=header.command,
                arg0=header.arg0,
                arg1=header.arg1,
                data_length=header.data_length,
                payload=header.payload,
                frame_number=transfer.frame_number,
                direction=transfer.direction,
            )

            if header.data_length == 0:
                # 无数据消息（OKAY, CLSE 等），直接完成
                messages.append(msg)
            elif len(header.payload) >= header.data_length:
                # 数据完全内联在头部帧中
                trimmed = AdbMessage(
                    command=msg.command,
                    arg0=msg.arg0,
                    arg1=msg.arg1,
                    data_length=msg.data_length,
                    payload=msg.payload[: msg.data_length],
                    frame_number=msg.frame_number,
                    direction=msg.direction,
                )
                messages.append(trimmed)
            else:
                # 数据不完整，等待后续帧
                pending_msg = msg
                pending_data.extend(header.payload)
        else:
            # 非 ADB 头：可能是前一个消息的数据帧
            if pending_msg is not None:
                pending_data.extend(payload)

                # 检查是否已收集够数据
                if len(pending_data) >= pending_msg.data_length:
                    completed = AdbMessage(
                        command=pending_msg.command,
                        arg0=pending_msg.arg0,
                        arg1=pending_msg.arg1,
                        data_length=pending_msg.data_length,
                        payload=bytes(pending_data[: pending_msg.data_length]),
                        frame_number=pending_msg.frame_number,
                        direction=pending_msg.direction,
                    )
                    messages.append(completed)
                    pending_msg = None
                    pending_data.clear()
            else:
                # 孤立的数据帧，记录但不丢弃
                logger.debug(
                    "帧 %d: 孤立数据帧 (%d bytes)",
                    transfer.frame_number,
                    len(payload),
                )

    # 处理末尾未完成的消息
    if pending_msg is not None:
        completed = AdbMessage(
            command=pending_msg.command,
            arg0=pending_msg.arg0,
            arg1=pending_msg.arg1,
            data_length=pending_msg.data_length,
            payload=bytes(pending_data),
            frame_number=pending_msg.frame_number,
            direction=pending_msg.direction,
        )
        messages.append(completed)

    logger.info("解析 ADB 消息: %d 条", len(messages))
    return messages


# ── Stream 重组 ────────────────────────────────────────────────────


def _reassemble_streams(messages: list[AdbMessage]) -> list[AdbStream]:
    """将 ADB 消息重组为逻辑 stream。

    ADB stream 生命周期：
        1. OPEN(local_id, 0, destination)  - Host 发起
        2. OKAY(remote_id, local_id)       - Device 确认
        3. WRTE(sender_id, receiver_id, data) - 双向数据
        4. CLSE(sender_id, receiver_id)    - 关闭

    参数:
        messages: ADB 消息列表。

    返回:
        按 OPEN 顺序排列的 stream 列表。
    """
    # stream key: local_id (host 端)
    stream_msgs: dict[int, list[AdbMessage]] = {}
    stream_dest: dict[int, str] = {}
    stream_remote: dict[int, int] = {}
    stream_order: list[int] = []

    for msg in messages:
        if msg.command == AdbCommand.OPEN and msg.direction == Direction.OUT:
            # Host 发起新 stream
            local_id = msg.arg0
            dest = msg.payload.rstrip(b"\x00").decode("utf-8", errors="replace")
            stream_dest[local_id] = dest
            stream_msgs[local_id] = [msg]
            stream_order.append(local_id)

        elif msg.command == AdbCommand.OKAY:
            if msg.direction == Direction.IN:
                # Device 确认: OKAY(remote_id, local_id)
                remote_id = msg.arg0
                local_id = msg.arg1
                stream_remote[local_id] = remote_id
                if local_id in stream_msgs:
                    stream_msgs[local_id].append(msg)
            else:
                # Host ACK: OKAY(local_id, remote_id)
                local_id = msg.arg0
                if local_id in stream_msgs:
                    stream_msgs[local_id].append(msg)
                else:
                    # 尝试通过 remote_id 查找
                    for lid, rid in stream_remote.items():
                        if rid == msg.arg1 and lid == msg.arg0:
                            stream_msgs[lid].append(msg)
                            break

        elif msg.command == AdbCommand.WRTE:
            # 查找对应 stream
            matched = False
            for lid in stream_msgs:
                rid = stream_remote.get(lid, -1)
                if (msg.arg0 == lid and msg.arg1 == rid) or (
                    msg.arg0 == rid and msg.arg1 == lid
                ):
                    stream_msgs[lid].append(msg)
                    matched = True
                    break
            if not matched:
                logger.debug(
                    "帧 %d: WRTE 无法匹配 stream (arg0=%d, arg1=%d)",
                    msg.frame_number,
                    msg.arg0,
                    msg.arg1,
                )

        elif msg.command == AdbCommand.CLSE:
            for lid in stream_msgs:
                rid = stream_remote.get(lid, -1)
                if (msg.arg0 == lid and msg.arg1 == rid) or (
                    msg.arg0 == rid and msg.arg1 == lid
                ) or (msg.arg1 == lid) or (msg.arg0 == lid):
                    stream_msgs[lid].append(msg)
                    break

        elif msg.command == AdbCommand.CNXN:
            # 连接消息不属于任何 stream，跳过
            pass

    # 构建 AdbStream 列表
    streams: list[AdbStream] = []
    for local_id in stream_order:
        dest = stream_dest.get(local_id, "")
        remote_id = stream_remote.get(local_id, 0)
        msgs = stream_msgs.get(local_id, [])

        streams.append(AdbStream(
            local_id=local_id,
            remote_id=remote_id,
            destination=dest,
            messages=tuple(msgs),
        ))

    logger.info("重组 ADB stream: %d 个", len(streams))
    return streams


# ── Sync 协议解析 ──────────────────────────────────────────────────

# Sync 命令标识（4 字节 ASCII）
_SYNC_STAT = b"STAT"
_SYNC_STA2 = b"STA2"
_SYNC_SEND = b"SEND"
_SYNC_SND2 = b"SND2"
_SYNC_DATA = b"DATA"
_SYNC_DONE = b"DONE"
_SYNC_OKAY = b"OKAY"
_SYNC_QUIT = b"QUIT"
_SYNC_RECV = b"RECV"


def _parse_sync_file_transfer(stream: AdbStream) -> SyncFileTransfer | None:
    """从 sync stream 中解析文件传输。

    Sync 协议用于 adb push/pull，传输流程：
        1. STA2 <path_len> <path>       - 查询文件状态
        2. STA2 <stat_result>           - 状态响应
        3. SND2 <path_len> <path>       - 开始发送
           SND2 <flags>                 - 发送标志
        4. DATA <chunk_len> <data>      - 数据块（重复多次）
        5. DONE <timestamp>             - 传输完成
        6. OKAY                         - 确认
        7. QUIT                         - 退出 sync

    注意: USBPcap 抓包可能因 snaplen 截断每个 USB 帧的数据，
    导致 DATA chunk 声明的长度大于实际捕获的数据。
    解析器必须容忍这种截断，尽可能多地恢复文件数据。

    参数:
        stream: destination 为 "sync:" 的 ADB stream。

    返回:
        文件传输信息（含可恢复的文件数据），或 None。
    """
    # 收集所有 WRTE 消息的数据
    wrte_data_out = bytearray()  # Host → Device
    wrte_data_in = bytearray()   # Device → Host
    declared_total = 0  # 声明的总传输数据量

    for msg in stream.messages:
        if msg.command != AdbCommand.WRTE:
            continue
        if msg.direction == Direction.OUT:
            wrte_data_out.extend(msg.payload)
            declared_total += msg.data_length
        else:
            wrte_data_in.extend(msg.payload)

    if len(wrte_data_out) < 8:
        return None

    # 已知 sync 命令标识（用于边界检测）
    known_sync_cmds = frozenset((
        _SYNC_STAT, _SYNC_STA2, _SYNC_SEND, _SYNC_SND2,
        _SYNC_DATA, _SYNC_DONE, _SYNC_OKAY, _SYNC_QUIT, _SYNC_RECV,
    ))

    # 解析 sync 命令序列
    remote_path = ""
    file_data = bytearray()

    pos = 0
    data = bytes(wrte_data_out)

    while pos + 4 <= len(data):
        cmd = data[pos: pos + 4]

        if pos + 8 > len(data):
            # 不足以读取 cmd + length，收集剩余作为原始数据
            file_data.extend(data[pos:])
            break

        if cmd in (_SYNC_STA2, _SYNC_STAT):
            # STAT/STA2: cmd(4) + path_len(4) + path(path_len)
            path_len = struct.unpack_from("<I", data, pos + 4)[0]
            if path_len < 4096 and pos + 8 + path_len <= len(data):
                path_str = data[pos + 8: pos + 8 + path_len].decode(
                    "utf-8", errors="replace"
                )
                if not remote_path:
                    remote_path = path_str
                logger.debug("Sync STAT: %s", path_str)
            pos += 8 + path_len

        elif cmd in (_SYNC_SND2, _SYNC_SEND):
            # SND2: cmd(4) + path_len(4) + path(path_len)
            path_len = struct.unpack_from("<I", data, pos + 4)[0]

            if path_len < 1024 and pos + 8 + path_len <= len(data):
                path_str = data[pos + 8: pos + 8 + path_len].decode(
                    "utf-8", errors="replace"
                )
                remote_path = path_str
                logger.debug("Sync SEND path: %s", path_str)
                pos += 8 + path_len
            else:
                pos += 8 + path_len

        elif cmd == _SYNC_DATA:
            # DATA: cmd(4) + chunk_len(4) + chunk_data(chunk_len)
            chunk_len = struct.unpack_from("<I", data, pos + 4)[0]
            chunk_start = pos + 8
            chunk_end = chunk_start + chunk_len

            # 取实际可用的数据（可能因 USBPcap snaplen 被截断）
            available_end = min(chunk_end, len(data))
            file_data.extend(data[chunk_start:available_end])

            # 推进位置：如果数据被截断，跳到数据末尾
            pos = available_end

        elif cmd == _SYNC_DONE:
            pos += 8
            break

        elif cmd == _SYNC_QUIT:
            pos += 8
            break

        elif cmd == _SYNC_OKAY:
            pos += 8

        else:
            # 不是已知 sync 命令头 — 这可能是被截断的 DATA 块的续接数据
            # 扫描到下一个已知 sync 命令边界，将中间数据作为文件内容
            next_cmd_pos = pos
            found_next = False
            scan_start = pos + 1

            for scan_pos in range(scan_start, len(data) - 3):
                if data[scan_pos: scan_pos + 4] in known_sync_cmds:
                    # 找到下一个 sync 命令
                    file_data.extend(data[pos:scan_pos])
                    pos = scan_pos
                    found_next = True
                    break

            if not found_next:
                # 没有更多 sync 命令，剩余全部作为文件数据
                file_data.extend(data[pos:])
                break

    if not file_data:
        return None

    result = SyncFileTransfer(
        remote_path=remote_path,
        file_data=bytes(file_data),
        file_size=len(file_data),
    )

    logger.info(
        "Sync 文件传输: %s (捕获 %d bytes, 声明 %d bytes)",
        result.remote_path,
        result.file_size,
        declared_total,
    )

    return result


# ── 高层命令提取 ────────────────────────────────────────────────────


def _extract_stream_output(stream: AdbStream) -> str:
    """提取 stream 中设备返回的所有文本输出。

    参数:
        stream: ADB stream。

    返回:
        设备返回的文本输出（合并所有 WRTE IN 消息）。
    """
    parts: list[str] = []

    for msg in stream.messages:
        if msg.command == AdbCommand.WRTE and msg.direction == Direction.IN:
            text = msg.payload.decode("utf-8", errors="replace")
            parts.append(text)

    return "".join(parts)


def _classify_stream(stream: AdbStream) -> tuple[CommandType, str]:
    """对 stream 进行命令分类。

    参数:
        stream: ADB stream。

    返回:
        (命令类型, 命令字符串) 元组。
    """
    dest = stream.destination

    if dest.startswith("reboot:"):
        target = dest[len("reboot:"):]
        cmd_str = f"reboot:{target}" if target else "reboot"
        return CommandType.REBOOT, cmd_str

    if dest.startswith("shell,v2,raw:"):
        cmd_str = dest[len("shell,v2,raw:"):]
        return CommandType.SHELL_V2, cmd_str

    if dest.startswith("shell,v2:"):
        cmd_str = dest[len("shell,v2:"):]
        return CommandType.SHELL_V2, cmd_str

    if dest.startswith("shell:"):
        cmd_str = dest[len("shell:"):]
        return CommandType.SHELL, cmd_str

    if dest == "sync:":
        return CommandType.PUSH, "sync"

    # 其他
    return CommandType.SHELL, dest


def _extract_connection_info(
    messages: list[AdbMessage],
) -> ConnectionInfo:
    """从 CNXN 消息中提取连接信息。

    参数:
        messages: 所有 ADB 消息。

    返回:
        连接信息。
    """
    host_features: list[str] = []
    device_banner = ""
    device_features: list[str] = []

    for msg in messages:
        if msg.command != AdbCommand.CNXN:
            continue

        banner = msg.payload.decode("utf-8", errors="replace").rstrip("\x00")

        if msg.direction == Direction.OUT:
            # Host banner: "host::features=..."
            if "features=" in banner:
                feat_str = banner.split("features=", 1)[1]
                host_features = feat_str.split(",")
        else:
            # Device banner: "recovery::prop1=val1;prop2=val2;features=..."
            device_banner = banner
            if "features=" in banner:
                feat_str = banner.split("features=", 1)[1]
                device_features = feat_str.split(",")

    return ConnectionInfo(
        host_features=tuple(host_features),
        device_banner=device_banner,
        device_features=tuple(device_features),
    )


def _extract_shell_v2_output(stream: AdbStream) -> str:
    """提取 shell v2 协议的命令输出。

    Shell v2 消息格式：
        id(1) + length(4, LE) + data(length)
        id=1: stdout, id=2: stderr, id=3: exit code

    参数:
        stream: shell v2 stream。

    返回:
        stdout + stderr 文本。
    """
    parts: list[str] = []

    for msg in stream.messages:
        if msg.command != AdbCommand.WRTE:
            continue
        if msg.direction == Direction.IN and len(msg.payload) >= 5:
            stream_id = msg.payload[0]
            data_len = struct.unpack_from("<I", msg.payload, 1)[0]
            data = msg.payload[5: 5 + data_len]
            if stream_id in (1, 2):
                parts.append(data.decode("utf-8", errors="replace"))
            elif stream_id == 3 and data_len == 1:
                exit_code = data[0] if data else -1
                parts.append(f"[exit code: {exit_code}]")

    return "".join(parts)


# ── 主解析流程 ─────────────────────────────────────────────────────


def parse_pcapng(file_path: Path | str) -> ParseResult:
    """解析 pcapng 文件，提取所有 ADB 命令序列。

    完整流程：
        1. pcapng → USB bulk transfer 帧
        2. USB 帧 → ADB 消息
        3. ADB 消息 → 逻辑 stream
        4. stream → 高层命令 + 文件传输

    参数:
        file_path: pcapng 文件路径。

    返回:
        完整的解析结果。
    """
    # Step 1: 解析 pcapng
    transfers = parse_pcapng_file(file_path)

    # Step 2: 解析 ADB 消息
    messages = parse_adb_messages(transfers)

    # Step 3: 提取连接信息
    connection = _extract_connection_info(messages)

    # Step 4: 重组 stream
    streams = _reassemble_streams(messages)

    # Step 5: 提取命令
    commands: list[ParsedCommand] = []
    step = 0

    for stream in streams:
        cmd_type, cmd_str = _classify_stream(stream)
        step += 1

        # 提取输出
        if cmd_type == CommandType.SHELL_V2:
            output = _extract_shell_v2_output(stream)
        elif cmd_type == CommandType.PUSH:
            output = ""
        else:
            output = _extract_stream_output(stream)

        # 提取文件传输
        file_transfer: SyncFileTransfer | None = None
        if cmd_type == CommandType.PUSH:
            file_transfer = _parse_sync_file_transfer(stream)
            if file_transfer:
                cmd_str = f"push → {file_transfer.remote_path}"

        commands.append(ParsedCommand(
            step=step,
            command_type=cmd_type,
            command=cmd_str,
            output=output,
            file_transfer=file_transfer,
            stream=stream,
        ))

    logger.info("提取命令: %d 个", len(commands))

    return ParseResult(
        source_file=str(file_path),
        total_usb_frames=len(transfers),
        total_adb_messages=len(messages),
        connection=connection,
        commands=tuple(commands),
    )
