"""
解析 5.0-Install Magisk && Root Phone.pcapng 中的 ADB 命令序列。

使用 tshark 提取 USB 捕获数据，解码 ADB 协议层，
还原完整的命令序列（OPEN/WRTE/CLSE/OKAY）。
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TSHARK_PATH = Path(r"C:\Program Files\Wireshark\tshark.exe")
PCAPNG_PATH = Path(
    r"d:\Code\IdeaProjects\google-one\WiresharkLog"
    r"\5.0-Install Magisk && Root Phone"
    r"\5.0-Install Magisk && Root Phone.pcapng"
)


@dataclass(frozen=True)
class UsbFrame:
    """单个 USB 帧。"""
    frame_number: int
    endpoint: int
    data_len: int
    raw_hex: str

    @property
    def raw_bytes(self) -> bytes:
        return bytes.fromhex(self.raw_hex) if self.raw_hex else b""

    @property
    def is_host_to_device(self) -> bool:
        """endpoint bit 7 = 0 → OUT (host → device)"""
        return (self.endpoint & 0x80) == 0

    @property
    def direction(self) -> str:
        return "H→D" if self.is_host_to_device else "D→H"


@dataclass(frozen=True)
class AdbMessage:
    """ADB 协议消息。"""
    frame_number: int
    direction: str
    command: str  # OPEN, OKAY, WRTE, CLSE, CNXN, AUTH
    arg0: int
    arg1: int
    data_length: int
    payload: bytes

    @property
    def payload_text(self) -> str:
        try:
            return self.payload.decode("utf-8", errors="replace")
        except Exception:
            return repr(self.payload)


# ADB 命令标识 (big-endian ASCII)
_ADB_COMMANDS: dict[bytes, str] = {
    b"OPEN": "OPEN",
    b"OKAY": "OKAY",
    b"WRTE": "WRTE",
    b"CLSE": "CLSE",
    b"CNXN": "CNXN",
    b"AUTH": "AUTH",
}


def extract_frames() -> list[UsbFrame]:
    """用 tshark 提取所有含 capdata 的 USB 帧。"""
    cmd = [
        str(TSHARK_PATH),
        "-r", str(PCAPNG_PATH),
        "-Y", "usb.capdata",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "usb.endpoint_address",
        "-e", "usb.data_len",
        "-e", "usb.capdata",
        "-E", "separator=|",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    frames: list[UsbFrame] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue
        try:
            frames.append(UsbFrame(
                frame_number=int(parts[0]),
                endpoint=int(parts[1], 16),
                data_len=int(parts[2]),
                raw_hex=parts[3].replace(":", ""),
            ))
        except (ValueError, IndexError):
            continue

    return frames


def parse_adb_messages(frames: list[UsbFrame]) -> list[AdbMessage]:
    """从 USB 帧中提取 ADB 协议消息。

    ADB 消息头固定 24 字节：
      - command (4 bytes, ASCII)
      - arg0    (4 bytes, little-endian uint32)
      - arg1    (4 bytes, little-endian uint32)
      - data_length (4 bytes, little-endian uint32)
      - data_crc32  (4 bytes)
      - magic   (4 bytes, = command ^ 0xFFFFFFFF)

    数据 payload 紧随消息头之后（可能在同一帧或后续帧中）。
    """
    messages: list[AdbMessage] = []
    i = 0

    while i < len(frames):
        frame = frames[i]
        raw = frame.raw_bytes

        # ADB 消息头至少 24 字节
        if len(raw) < 24:
            i += 1
            continue

        cmd_bytes = raw[:4]
        if cmd_bytes not in _ADB_COMMANDS:
            i += 1
            continue

        cmd_name = _ADB_COMMANDS[cmd_bytes]
        arg0 = int.from_bytes(raw[4:8], "little")
        arg1 = int.from_bytes(raw[8:12], "little")
        data_length = int.from_bytes(raw[12:16], "little")

        # 收集 payload
        payload = b""
        if data_length > 0:
            # 如果当前帧头之后还有数据
            if len(raw) > 24:
                payload = raw[24:24 + data_length]
            # 如果数据不够，查看后续帧
            if len(payload) < data_length:
                j = i + 1
                while j < len(frames) and len(payload) < data_length:
                    next_frame = frames[j]
                    next_raw = next_frame.raw_bytes
                    # 后续帧如果不是 ADB 消息头，就是数据续传
                    if len(next_raw) >= 4 and next_raw[:4] in _ADB_COMMANDS:
                        break
                    payload += next_raw
                    j += 1

        messages.append(AdbMessage(
            frame_number=frame.frame_number,
            direction=frame.direction,
            command=cmd_name,
            arg0=arg0,
            arg1=arg1,
            data_length=data_length,
            payload=payload[:data_length] if data_length > 0 else b"",
        ))

        i += 1

    return messages


def decode_command_sequence(messages: list[AdbMessage]) -> None:
    """解码并打印完整的 ADB 命令序列。"""
    # 跟踪活跃的 stream（local_id → 已知信息）
    streams: dict[int, dict[str, str]] = {}

    print("=" * 80)
    print("ADB 命令序列 — 5.0-Install Magisk && Root Phone.pcapng")
    print("=" * 80)
    print()

    step = 0

    for msg in messages:
        if msg.command == "CNXN":
            text = msg.payload_text.rstrip("\x00")
            print(f"[Frame {msg.frame_number}] {msg.direction} CNXN: {text}")
            print()

        elif msg.command == "OPEN":
            text = msg.payload_text.rstrip("\x00")
            local_id = msg.arg0
            streams[local_id] = {"service": text, "output": ""}

            step += 1
            print(f"--- Step {step} ---")
            print(f"[Frame {msg.frame_number}] {msg.direction} OPEN "
                  f"local_id={local_id:#x}")
            print(f"  Service: {text}")

        elif msg.command == "WRTE":
            if msg.data_length > 0:
                payload = msg.payload
                text = msg.payload_text

                # 检测是否是可打印文本
                printable_ratio = sum(
                    1 for b in payload
                    if 0x20 <= b <= 0x7E or b in (0x0A, 0x0D, 0x09)
                ) / max(len(payload), 1)

                if printable_ratio > 0.7:
                    # 显示文本内容
                    clean = text.rstrip("\x00").strip()
                    if clean:
                        print(f"[Frame {msg.frame_number}] {msg.direction} WRTE "
                              f"({msg.data_length} bytes):")
                        for line in clean.split("\n"):
                            print(f"    {line}")
                else:
                    # 二进制数据（如文件传输）
                    # 检查是否是 ADB SYNC 协议
                    if len(payload) >= 4:
                        sync_cmd = payload[:4]
                        if sync_cmd in (b"SEND", b"DATA", b"DONE", b"RECV",
                                        b"STAT", b"QUIT", b"OKAY"):
                            print(f"[Frame {msg.frame_number}] {msg.direction} WRTE "
                                  f"SYNC:{sync_cmd.decode()} "
                                  f"({msg.data_length} bytes)")
                        else:
                            print(f"[Frame {msg.frame_number}] {msg.direction} WRTE "
                                  f"binary ({msg.data_length} bytes)")
                    else:
                        print(f"[Frame {msg.frame_number}] {msg.direction} WRTE "
                              f"({msg.data_length} bytes)")

        elif msg.command == "CLSE":
            local_id = msg.arg0
            remote_id = msg.arg1
            print(f"[Frame {msg.frame_number}] {msg.direction} CLSE "
                  f"local={local_id:#x} remote={remote_id:#x}")
            print()

        elif msg.command == "OKAY":
            pass  # 静默 ACK

    print("=" * 80)
    print("解析完成")
    print("=" * 80)


def main() -> None:
    print(f"tshark: {TSHARK_PATH}")
    print(f"pcapng: {PCAPNG_PATH}")
    print()

    print("正在提取 USB 帧...")
    frames = extract_frames()
    print(f"共提取 {len(frames)} 个含数据的 USB 帧")
    print()

    print("正在解析 ADB 消息...")
    messages = parse_adb_messages(frames)
    print(f"共解析 {len(messages)} 条 ADB 消息")
    print()

    decode_command_sequence(messages)


if __name__ == "__main__":
    main()
