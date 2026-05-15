"""
解析 7.0-Randomly change device.pcapng 抓包文件。

使用 tshark 导出 USB BULK 传输的原始载荷，逐字节解析 ADB 协议，
将多包（header + payload 分离）正确拼接后提取所有命令及响应。
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
PCAPNG = (
    Path(__file__).resolve().parent
    / "WiresharkLog"
    / "7.0-Randomly change device"
    / "7.0-Randomly change device.pcapng"
)

# ADB protocol command identifiers (little-endian uint32)
ADB_COMMANDS: dict[int, str] = {
    0x4e584e43: "CNXN",
    0x4e45504f: "OPEN",
    0x59414b4f: "OKAY",
    0x45545257: "WRTE",
    0x45534c43: "CLSE",
    0x48545541: "AUTH",
}


def extract_packets() -> list[tuple[int, str, str, int, bytes]]:
    """使用 tshark 导出所有含 capdata 的 USB BULK 包。"""
    cmd = [
        TSHARK,
        "-r", str(PCAPNG),
        "-T", "fields",
        "-e", "frame.number",
        "-e", "usb.src",
        "-e", "usb.dst",
        "-e", "usb.data_len",
        "-e", "usb.capdata",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    packets: list[tuple[int, str, str, int, bytes]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 5 or not parts[4]:
            continue
        frame_num = int(parts[0])
        src = parts[1]
        dst = parts[2]
        data_len = int(parts[3])
        raw = bytes.fromhex(parts[4])
        packets.append((frame_num, src, dst, data_len, raw))
    return packets


def try_parse_adb_header(data: bytes) -> tuple[str, int, int, int] | None:
    """尝试解析 24 字节 ADB 消息头。"""
    if len(data) < 24:
        return None
    command, arg0, arg1, data_length, data_crc, magic = struct.unpack(
        "<IIIIII", data[:24]
    )
    cmd_name = ADB_COMMANDS.get(command)
    if cmd_name is None:
        return None
    # Validate magic: magic should be command ^ 0xFFFFFFFF
    if magic != (command ^ 0xFFFFFFFF):
        return None
    return cmd_name, arg0, arg1, data_length


def main() -> None:
    """解析并打印所有 ADB 命令序列。"""
    print(f"解析: {PCAPNG}")
    print()

    packets = extract_packets()
    print(f"含 capdata 的包总数: {len(packets)}")
    print()

    # Reassemble ADB messages: header (24B) and payload may be in separate USB packets
    # We need to correlate header packets with their payload packets
    pending_header: dict[str, tuple[int, str, int, int, int, int]] = {}
    # key: direction ("h2d" or "d2h") -> (frame, cmd_name, arg0, arg1, expected_len, collected_len)
    pending_payload: dict[str, bytearray] = {}

    # Track streams
    streams: dict[int, str] = {}  # local_id -> stream purpose
    open_commands: list[tuple[int, str]] = []  # (frame_num, command)
    
    # Output file
    output_lines: list[str] = []

    def process_message(
        frame_num: int,
        cmd_name: str,
        arg0: int,
        arg1: int,
        payload: bytes,
        from_host: bool,
    ) -> None:
        """处理一条完整的 ADB 消息。"""
        if cmd_name == "CNXN":
            text = payload.decode("utf-8", errors="replace").rstrip("\x00")
            line = f"[{frame_num:>6}] CNXN  {text}"
            output_lines.append(line)

        elif cmd_name == "AUTH":
            line = f"[{frame_num:>6}] AUTH  (type={arg0})"
            output_lines.append(line)

        elif cmd_name == "OPEN":
            text = payload.decode("utf-8", errors="replace").rstrip("\x00")
            local_id = arg0
            streams[local_id] = text
            open_commands.append((frame_num, text))
            line = f"[{frame_num:>6}] OPEN  → {text}"
            output_lines.append(line)

        elif cmd_name == "WRTE":
            if not payload:
                return
            # Skip pure control bytes (stdin close / exit status)
            if len(payload) <= 6 and all(b < 0x20 for b in payload):
                return
            # Try to determine stream name
            stream = streams.get(arg1, streams.get(arg0, "?"))
            text = payload.decode("utf-8", errors="replace").rstrip("\x00").strip()
            if not text:
                return
            direction = "→" if from_host else "←"
            display = text[:500].replace("\n", "\\n")
            line = f"[{frame_num:>6}]   {direction} [{stream}] {display}"
            output_lines.append(line)

        elif cmd_name == "CLSE":
            pass  # Stream close, skip for readability

        elif cmd_name == "OKAY":
            pass  # ACK, skip

    for frame_num, src, dst, data_len, raw in packets:
        from_host = "host" in src
        direction_key = "h2d" if from_host else "d2h"

        # Check if we're waiting for a payload
        if direction_key in pending_header:
            ph = pending_header[direction_key]
            ph_frame, ph_cmd, ph_arg0, ph_arg1, expected_len, collected = ph

            if direction_key not in pending_payload:
                pending_payload[direction_key] = bytearray()

            pending_payload[direction_key].extend(raw)
            collected += len(raw)

            if collected >= expected_len:
                # We have the full payload
                full_payload = bytes(pending_payload[direction_key][:expected_len])
                process_message(ph_frame, ph_cmd, ph_arg0, ph_arg1, full_payload, from_host)
                del pending_header[direction_key]
                del pending_payload[direction_key]
                continue
            else:
                # Still collecting
                pending_header[direction_key] = (
                    ph_frame, ph_cmd, ph_arg0, ph_arg1, expected_len, collected,
                )
                continue

        # Try to parse as ADB header
        header = try_parse_adb_header(raw)
        if header is None:
            continue

        cmd_name, arg0, arg1, data_length = header
        inline_payload = raw[24:]

        if data_length == 0:
            # No payload expected
            process_message(frame_num, cmd_name, arg0, arg1, b"", from_host)
        elif len(inline_payload) >= data_length:
            # Payload is inline with header
            process_message(
                frame_num, cmd_name, arg0, arg1,
                inline_payload[:data_length], from_host,
            )
        else:
            # Payload will come in subsequent packet(s)
            pending_header[direction_key] = (
                frame_num, cmd_name, arg0, arg1,
                data_length, len(inline_payload),
            )
            pending_payload[direction_key] = bytearray(inline_payload)

    # Print all output
    for line in output_lines:
        print(line)

    print()
    print("=" * 70)
    print("完整命令序列（OPEN 命令，按顺序）:")
    print("=" * 70)
    for i, (frame, cmd) in enumerate(open_commands, 1):
        print(f"  {i:>3}. [{frame:>6}] {cmd}")

    # Write to file as well
    out_path = Path(__file__).resolve().parent / "parse_output_7.0.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for line in output_lines:
            f.write(line + "\n")
        f.write("\n")
        f.write("=" * 70 + "\n")
        f.write("完整命令序列（OPEN 命令，按顺序）:\n")
        f.write("=" * 70 + "\n")
        for i, (frame, cmd) in enumerate(open_commands, 1):
            f.write(f"  {i:>3}. [{frame:>6}] {cmd}\n")
    print(f"\n输出已保存到: {out_path}")


if __name__ == "__main__":
    main()
