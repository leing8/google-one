"""Parse 8.0-Update Integrity Fix.pcapng using tshark to extract all ADB commands.

Follows the same proven pattern as parse_install_modules.py.
"""

import io
import json
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
PCAPNG = Path(
    r"d:\Code\IdeaProjects\google-one\WiresharkLog"
    r"\8.0-Update Integrity Fix\8.0-Update Integrity Fix.pcapng"
)


@dataclass(frozen=True)
class AdbMessage:
    frame: int
    direction: str  # "OUT" (host->device) or "IN" (device->host)
    command: str
    arg0: int
    arg1: int
    data_len: int
    payload: bytes


def extract_raw_frames() -> list[tuple[int, str, bytes]]:
    """Extract all USB bulk transfer frames with raw data using tshark."""
    result = subprocess.run(
        [
            TSHARK,
            "-r", str(PCAPNG),
            "-T", "fields",
            "-e", "frame.number",
            "-e", "usb.endpoint_address",
            "-e", "usb.data_len",
            "-e", "usb.capdata",
            "-Y", "usb.data_len > 0",
            "-E", "separator=|",
        ],
        capture_output=True,
        text=True,
    )

    frames: list[tuple[int, str, bytes]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue

        frame_num = int(parts[0])
        endpoint = int(parts[1], 16)
        hex_data = parts[3].replace(":", "")

        # Direction: endpoint bit 7 = 1 means IN (device->host)
        direction = "IN" if (endpoint & 0x80) else "OUT"

        try:
            raw_data = bytes.fromhex(hex_data)
        except ValueError:
            continue

        frames.append((frame_num, direction, raw_data))

    return frames


def parse_adb_header(data: bytes) -> tuple[str, int, int, int] | None:
    """Parse ADB message header (24 bytes)."""
    if len(data) < 24:
        return None

    cmd_bytes = data[0:4]
    cmd_str = cmd_bytes.decode("ascii", errors="ignore")

    if cmd_str not in ("CNXN", "OPEN", "OKAY", "CLSE", "WRTE", "AUTH", "STLS"):
        return None

    arg0, arg1, data_length, data_crc, magic = struct.unpack_from("<IIIII", data, 4)

    # Verify magic
    cmd_int = struct.unpack_from("<I", data, 0)[0]
    expected_magic = cmd_int ^ 0xFFFFFFFF
    if magic != expected_magic:
        return None

    return (cmd_str, arg0, arg1, data_length)


def parse_all_messages(frames: list[tuple[int, str, bytes]]) -> list[AdbMessage]:
    """Parse all ADB messages from raw USB frames."""
    messages: list[AdbMessage] = []
    i = 0

    while i < len(frames):
        frame_num, direction, data = frames[i]

        header = parse_adb_header(data)
        if header is None:
            i += 1
            continue

        cmd_str, arg0, arg1, data_length = header

        payload = b""
        if data_length > 0:
            if len(data) > 24:
                payload = data[24:24 + data_length]
            else:
                remaining = data_length
                j = i + 1
                while remaining > 0 and j < len(frames):
                    _, next_dir, next_data = frames[j]
                    if next_dir == direction and parse_adb_header(next_data) is None:
                        payload += next_data[:remaining]
                        remaining -= len(next_data)
                        j += 1
                    else:
                        break
                i = j - 1

        messages.append(AdbMessage(
            frame=frame_num,
            direction=direction,
            command=cmd_str,
            arg0=arg0,
            arg1=arg1,
            data_len=data_length,
            payload=payload,
        ))

        i += 1

    return messages


def decode_payload(payload: bytes) -> str:
    """Decode ADB payload to readable string."""
    try:
        text = payload.decode("utf-8", errors="replace").rstrip("\x00").strip()
        return text
    except Exception:
        return payload.hex()[:100]


def analyze_messages(messages: list[AdbMessage]) -> None:
    """Analyze and print all ADB command flows."""
    streams: dict[int, str] = {}

    print(f"{'=' * 80}")
    print("ADB Protocol Analysis: 8.0-Update Integrity Fix.pcapng")
    print(f"Total ADB messages: {len(messages)}")
    print(f"{'=' * 80}\n")

    for msg in messages:
        arrow = "->" if msg.direction == "OUT" else "<-"

        if msg.command == "CNXN":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            print(
                f"[Frame {msg.frame:4d}] {arrow} CNXN version={msg.arg0:#x} "
                f"maxdata={msg.arg1} payload={payload_str}"
            )

        elif msg.command == "AUTH":
            auth_type = {
                1: "TOKEN", 2: "SIGNATURE", 3: "RSAPUBLICKEY"
            }.get(msg.arg0, f"UNKNOWN({msg.arg0})")
            print(f"[Frame {msg.frame:4d}] {arrow} AUTH type={auth_type}")

        elif msg.command == "STLS":
            print(
                f"[Frame {msg.frame:4d}] {arrow} STLS "
                f"arg0={msg.arg0} arg1={msg.arg1}"
            )

        elif msg.command == "OPEN":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            streams[msg.arg0] = payload_str
            print(
                f"[Frame {msg.frame:4d}] {arrow} OPEN local_id={msg.arg0} "
                f"remote_id={msg.arg1} service=\"{payload_str}\""
            )

        elif msg.command == "OKAY":
            pass  # Skip OKAY messages for cleaner output

        elif msg.command == "WRTE":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            if msg.data_len > 200:
                if msg.payload[:4] in (
                    b'SEND', b'DATA', b'DONE', b'STAT', b'RECV',
                    b'QUIT', b'LIST', b'DENT',
                    b'SND2', b'STA2', b'RCV2', b'LST2', b'DNT2',
                ):
                    sync_cmd = msg.payload[:4].decode()
                    print(
                        f"[Frame {msg.frame:4d}] {arrow} WRTE SYNC:{sync_cmd} "
                        f"local={msg.arg0} remote={msg.arg1} len={msg.data_len}"
                    )
                else:
                    print(
                        f"[Frame {msg.frame:4d}] {arrow} WRTE local={msg.arg0} "
                        f"remote={msg.arg1} len={msg.data_len} [binary data]"
                    )
            else:
                if payload_str:
                    print(
                        f"[Frame {msg.frame:4d}] {arrow} WRTE local={msg.arg0} "
                        f"remote={msg.arg1} data=\"{payload_str}\""
                    )

        elif msg.command == "CLSE":
            print(
                f"[Frame {msg.frame:4d}] {arrow} CLSE "
                f"local={msg.arg0} remote={msg.arg1}"
            )


def extract_command_sequence(messages: list[AdbMessage]) -> list[dict]:
    """Extract the ordered sequence of ADB shell/sync commands."""
    commands: list[dict] = []

    # Track open service per local_id
    open_services: dict[int, str] = {}

    for msg in messages:
        if msg.command == "OPEN" and msg.payload:
            service = decode_payload(msg.payload)
            open_services[msg.arg0] = service
            commands.append({
                "frame": msg.frame,
                "direction": msg.direction,
                "type": "OPEN",
                "service": service,
                "local_id": msg.arg0,
            })

        elif msg.command == "WRTE" and msg.payload:
            payload_str = decode_payload(msg.payload)

            # Check for SYNC protocol
            if len(msg.payload) >= 4:
                sync_cmd = msg.payload[:4]
                sync_cmds = (
                    b'SEND', b'DATA', b'DONE', b'STAT', b'RECV', b'QUIT',
                    b'LIST', b'DENT', b'SND2', b'STA2', b'RCV2', b'LST2',
                    b'DNT2',
                )
                if sync_cmd in sync_cmds:
                    sync_name = sync_cmd.decode()
                    if sync_name in ('SEND', 'RECV', 'STAT', 'LIST', 'SND2', 'STA2', 'RCV2', 'LST2'):
                        path_len = (
                            struct.unpack_from("<I", msg.payload, 4)[0]
                            if len(msg.payload) >= 8 else 0
                        )
                        path = (
                            msg.payload[8:8 + path_len].decode("utf-8", errors="replace")
                            if path_len > 0 else ""
                        )
                        commands.append({
                            "frame": msg.frame,
                            "direction": msg.direction,
                            "type": f"SYNC:{sync_name}",
                            "path": path,
                            "data_len": msg.data_len,
                        })
                    elif sync_name == 'DATA':
                        data_size = (
                            struct.unpack_from("<I", msg.payload, 4)[0]
                            if len(msg.payload) >= 8 else 0
                        )
                        commands.append({
                            "frame": msg.frame,
                            "direction": msg.direction,
                            "type": "SYNC:DATA",
                            "chunk_size": data_size,
                            "data_len": msg.data_len,
                        })
                    elif sync_name == 'DONE':
                        commands.append({
                            "frame": msg.frame,
                            "direction": msg.direction,
                            "type": "SYNC:DONE",
                        })
                    else:
                        commands.append({
                            "frame": msg.frame,
                            "direction": msg.direction,
                            "type": f"SYNC:{sync_name}",
                            "data_len": msg.data_len,
                        })
                    continue

            # Regular text payload
            if payload_str and not all(c in '\x00\xff' for c in payload_str[:10]):
                commands.append({
                    "frame": msg.frame,
                    "direction": msg.direction,
                    "type": "WRTE",
                    "data": payload_str[:1000],
                    "data_len": msg.data_len,
                    "local_id": msg.arg0,
                    "remote_id": msg.arg1,
                })

        elif msg.command == "CLSE":
            commands.append({
                "frame": msg.frame,
                "direction": msg.direction,
                "type": "CLSE",
                "local_id": msg.arg0,
                "remote_id": msg.arg1,
            })

    return commands


def main() -> None:
    print("Extracting USB frames with tshark...")
    frames = extract_raw_frames()
    print(f"Found {len(frames)} USB frames with data")

    print("Parsing ADB messages...")
    messages = parse_all_messages(frames)
    print(f"Found {len(messages)} ADB messages")

    # Full analysis
    analyze_messages(messages)

    # Extract command sequence
    print(f"\n{'=' * 80}")
    print("COMMAND SEQUENCE SUMMARY")
    print(f"{'=' * 80}\n")

    commands = extract_command_sequence(messages)
    for cmd in commands:
        print(json.dumps(cmd, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
