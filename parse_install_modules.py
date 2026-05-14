"""Parse 6.0-Install Modules.pcapng using tshark to extract all ADB commands."""

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
PCAPNG = Path(r"d:\Code\IdeaProjects\google-one\WiresharkLog\6.0-Install Modules\6.0-Install Modules.pcapng")

# ADB protocol constants
ADB_COMMAND_NAMES = {
    0x434e5953: "CNXN",  # CONNECT
    0x4e584e43: "CNXN",  # CONNECT (reversed)
    0x4e45504f: "OPEN",  # OPEN
    0x45504f4e: "OPEN",  # OPEN (reversed)
    0x45545257: "WRTE",  # WRITE
    0x45545257: "WRTE",  # WRITE
    0x59414b4f: "OKAY",  # OKAY
    0x59414b4f: "OKAY",  # OKAY
    0x45534c43: "CLSE",  # CLOSE
    0x45534c43: "CLSE",  # CLOSE
    0x48545541: "AUTH",  # AUTH
}

# Correct ADB magic values
ADB_CMDS = {
    b'CNXN': 'CNXN',
    b'OPEN': 'OPEN', 
    b'OKAY': 'OKAY',
    b'CLSE': 'CLSE',
    b'WRTE': 'WRTE',
    b'AUTH': 'AUTH',
    b'STLS': 'STLS',
}


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
    
    frames = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|")
        if len(parts) < 4:
            continue
        
        frame_num = int(parts[0])
        endpoint = int(parts[1], 16)
        data_len = int(parts[2])
        hex_data = parts[3].replace(":", "")
        
        # Direction: endpoint bit 7 = 1 means IN (device->host), 0 means OUT (host->device)
        direction = "IN" if (endpoint & 0x80) else "OUT"
        
        try:
            raw_data = bytes.fromhex(hex_data)
        except ValueError:
            continue
        
        frames.append((frame_num, direction, raw_data))
    
    return frames


def parse_adb_header(data: bytes) -> tuple[str, int, int, int] | None:
    """Parse ADB message header (24 bytes).
    
    ADB header format:
    - command (4 bytes): ASCII command name
    - arg0 (4 bytes LE)
    - arg1 (4 bytes LE)
    - data_length (4 bytes LE)
    - data_crc32 (4 bytes LE)
    - magic (4 bytes LE): command ^ 0xFFFFFFFF
    """
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
    messages = []
    i = 0
    
    while i < len(frames):
        frame_num, direction, data = frames[i]
        
        header = parse_adb_header(data)
        if header is None:
            i += 1
            continue
        
        cmd_str, arg0, arg1, data_length = header
        
        # If data_length > 0, the payload is in the next frame(s)
        payload = b""
        if data_length > 0:
            # Check if payload is in the same frame (after header)
            if len(data) > 24:
                payload = data[24:24 + data_length]
            else:
                # Look for payload in next frame(s)
                remaining = data_length
                j = i + 1
                while remaining > 0 and j < len(frames):
                    _, next_dir, next_data = frames[j]
                    # Next frame should be same direction and NOT an ADB header
                    if next_dir == direction and parse_adb_header(next_data) is None:
                        payload += next_data[:remaining]
                        remaining -= len(next_data)
                        j += 1
                    else:
                        break
                i = j - 1  # Will be incremented at end
        
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
    # Track streams (local_id -> service/purpose)
    streams: dict[int, str] = {}
    
    print(f"{'='*80}")
    print(f"ADB Protocol Analysis: 6.0-Install Modules.pcapng")
    print(f"Total ADB messages: {len(messages)}")
    print(f"{'='*80}\n")
    
    for msg in messages:
        arrow = "->" if msg.direction == "OUT" else "<-"
        
        if msg.command == "CNXN":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            print(f"[Frame {msg.frame:4d}] {arrow} CNXN version={msg.arg0:#x} maxdata={msg.arg1} payload={payload_str}")
        
        elif msg.command == "AUTH":
            auth_type = {1: "TOKEN", 2: "SIGNATURE", 3: "RSAPUBLICKEY"}.get(msg.arg0, f"UNKNOWN({msg.arg0})")
            print(f"[Frame {msg.frame:4d}] {arrow} AUTH type={auth_type}")
        
        elif msg.command == "STLS":
            print(f"[Frame {msg.frame:4d}] {arrow} STLS arg0={msg.arg0} arg1={msg.arg1}")
        
        elif msg.command == "OPEN":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            streams[msg.arg0] = payload_str
            print(f"[Frame {msg.frame:4d}] {arrow} OPEN local_id={msg.arg0} remote_id={msg.arg1} service=\"{payload_str}\"")
        
        elif msg.command == "OKAY":
            pass  # Skip OKAY messages for cleaner output
        
        elif msg.command == "WRTE":
            payload_str = decode_payload(msg.payload) if msg.payload else ""
            # Only print non-binary payloads or summarize binary ones
            if msg.data_len > 200:
                # Check if it's a SYNC protocol transfer
                if msg.payload[:4] in (b'SEND', b'DATA', b'DONE', b'STAT', b'RECV', b'QUIT', b'LIST', b'DENT'):
                    sync_cmd = msg.payload[:4].decode()
                    print(f"[Frame {msg.frame:4d}] {arrow} WRTE SYNC:{sync_cmd} local={msg.arg0} remote={msg.arg1} len={msg.data_len}")
                else:
                    print(f"[Frame {msg.frame:4d}] {arrow} WRTE local={msg.arg0} remote={msg.arg1} len={msg.data_len} [binary data]")
            else:
                # Show text payload
                if payload_str:
                    print(f"[Frame {msg.frame:4d}] {arrow} WRTE local={msg.arg0} remote={msg.arg1} data=\"{payload_str}\"")
        
        elif msg.command == "CLSE":
            print(f"[Frame {msg.frame:4d}] {arrow} CLSE local={msg.arg0} remote={msg.arg1}")


def extract_command_sequence(messages: list[AdbMessage]) -> list[dict]:
    """Extract the ordered sequence of ADB shell/sync commands."""
    commands = []
    
    for msg in messages:
        if msg.command == "OPEN" and msg.payload:
            service = decode_payload(msg.payload)
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
                if sync_cmd in (b'SEND', b'DATA', b'DONE', b'STAT', b'RECV', b'QUIT', b'LIST', b'DENT'):
                    # Parse SYNC command
                    sync_name = sync_cmd.decode()
                    if sync_name in ('SEND', 'RECV', 'STAT', 'LIST'):
                        # These have a path following
                        path_len = struct.unpack_from("<I", msg.payload, 4)[0] if len(msg.payload) >= 8 else 0
                        path = msg.payload[8:8+path_len].decode("utf-8", errors="replace") if path_len > 0 else ""
                        commands.append({
                            "frame": msg.frame,
                            "direction": msg.direction,
                            "type": f"SYNC:{sync_name}",
                            "path": path,
                            "data_len": msg.data_len,
                        })
                    elif sync_name == 'DATA':
                        data_size = struct.unpack_from("<I", msg.payload, 4)[0] if len(msg.payload) >= 8 else 0
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
                    "data": payload_str[:500],
                    "data_len": msg.data_len,
                    "local_id": msg.arg0,
                    "remote_id": msg.arg1,
                })
    
    return commands


def main() -> None:
    print("Extracting USB frames with tshark...")
    frames = extract_raw_frames()
    print(f"Found {len(frames)} USB frames with data")
    
    print("Parsing ADB messages...")
    messages = parse_adb_messages(frames)
    print(f"Found {len(messages)} ADB messages")
    
    # Full analysis
    analyze_messages(messages)
    
    # Extract command sequence
    print(f"\n{'='*80}")
    print("COMMAND SEQUENCE SUMMARY")
    print(f"{'='*80}\n")
    
    commands = extract_command_sequence(messages)
    for cmd in commands:
        print(json.dumps(cmd, indent=2, ensure_ascii=False))
        print()


def parse_adb_messages(frames):
    return parse_all_messages(frames)


if __name__ == "__main__":
    main()
