"""pcapng 文件二进制解析器。

严格按照 pcapng 文件格式规范解析：
- Section Header Block (SHB)
- Interface Description Block (IDB)
- Enhanced Packet Block (EPB)

从 EPB 中提取 USBPcap 帧，过滤 USB bulk transfer 数据载荷。

参考:
    https://pcapng.com/
    https://www.tcpdump.org/linktypes/LINKTYPE_USB_LINUX.html

使用 Python 标准库 struct 模块进行二进制解码。
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

from parse_models import Direction, UsbBulkTransfer

logger = logging.getLogger(__name__)

# ── pcapng 块类型常量 ──────────────────────────────────────────────

_SHB_TYPE: int = 0x0A0D0D0A  # Section Header Block
_IDB_TYPE: int = 0x00000001  # Interface Description Block
_EPB_TYPE: int = 0x00000006  # Enhanced Packet Block
_SPB_TYPE: int = 0x00000003  # Simple Packet Block

# ── USBPcap 常量 ───────────────────────────────────────────────────

_USB_TRANSFER_BULK: int = 3  # Bulk transfer type
_MIN_USBPCAP_HEADER: int = 27  # 最小 USBPcap 头长度
_MIN_BLOCK_SIZE: int = 12  # pcapng 块的最小大小


@dataclass(frozen=True)
class _PcapngBlock:
    """内部：单个 pcapng 块。"""

    block_type: int
    body: bytes
    offset: int


def _iter_blocks(data: bytes) -> list[_PcapngBlock]:
    """迭代解析 pcapng 文件中的所有块。

    pcapng 块通用格式：
        block_type (4 bytes, LE uint32)
        block_total_length (4 bytes, LE uint32)
        block_body (variable)
        block_total_length (4 bytes, LE uint32, repeated)

    参数:
        data: pcapng 文件的完整二进制数据。

    返回:
        解析出的 pcapng 块列表。
    """
    blocks: list[_PcapngBlock] = []
    pos = 0

    while pos + 8 <= len(data):
        block_type, block_total_len = struct.unpack_from("<II", data, pos)

        # 合法性检查
        if block_total_len < _MIN_BLOCK_SIZE:
            logger.warning(
                "偏移 0x%06x: 块大小 %d 小于最小值 %d, 停止解析",
                pos,
                block_total_len,
                _MIN_BLOCK_SIZE,
            )
            break

        if pos + block_total_len > len(data):
            logger.warning(
                "偏移 0x%06x: 块大小 %d 超出文件边界, 停止解析",
                pos,
                block_total_len,
            )
            break

        # 块体：去掉头部 8 字节和尾部 4 字节（重复的 block_total_length）
        body_start = pos + 8
        body_end = pos + block_total_len - 4
        body = data[body_start:body_end] if body_end > body_start else b""

        blocks.append(_PcapngBlock(
            block_type=block_type,
            body=body,
            offset=pos,
        ))

        pos += block_total_len

    logger.info("pcapng 块总数: %d", len(blocks))
    return blocks


def _parse_epb_to_usb_bulk(
    block: _PcapngBlock,
    frame_number: int,
) -> UsbBulkTransfer | None:
    """从 Enhanced Packet Block 中提取 USB bulk transfer 载荷。

    EPB body 格式：
        interface_id (4 bytes, LE uint32)
        timestamp_high (4 bytes, LE uint32)
        timestamp_low (4 bytes, LE uint32)
        captured_packet_length (4 bytes, LE uint32)
        original_packet_length (4 bytes, LE uint32)
        packet_data (captured_packet_length bytes)
        [options + padding]

    USBPcap 头格式 (前 27+ 字节):
        headerLen (2 bytes, LE uint16) - 头部总长度
        irpId (8 bytes)
        status (4 bytes)
        function (2 bytes)
        info (1 byte)
        bus (2 bytes)
        device (2 bytes)
        endpoint (1 byte)         - bit 7 = direction
        transfer (1 byte)         - 3 = bulk
        dataLength (4 bytes, LE uint32)

    参数:
        block: EPB pcapng 块。
        frame_number: 帧编号。

    返回:
        如果是包含数据的 USB bulk transfer，返回 UsbBulkTransfer；否则 None。
    """
    body = block.body

    if len(body) < 20:
        return None

    captured_len = struct.unpack_from("<I", body, 12)[0]

    packet_data = body[20: 20 + captured_len]

    if len(packet_data) < _MIN_USBPCAP_HEADER:
        return None

    # 解析 USBPcap 头
    header_len = struct.unpack_from("<H", packet_data, 0)[0]

    if header_len < _MIN_USBPCAP_HEADER or header_len > len(packet_data):
        return None

    # endpoint 在偏移 21, transfer_type 在偏移 22, dataLength 在偏移 23
    endpoint_byte = packet_data[21]
    transfer_type = packet_data[22]
    usb_data_length = struct.unpack_from("<I", packet_data, 23)[0]

    if transfer_type != _USB_TRANSFER_BULK:
        return None

    # 提取载荷（可能被 USBPcap snaplen 截断）
    usb_payload = packet_data[header_len:]

    if len(usb_payload) == 0:
        return None

    # 方向：endpoint byte 的 bit 7
    direction = Direction.IN if (endpoint_byte >> 7) & 1 else Direction.OUT

    return UsbBulkTransfer(
        frame_number=frame_number,
        direction=direction,
        payload=usb_payload,
        usb_data_length=usb_data_length,
    )


def parse_pcapng_file(file_path: Path | str) -> list[UsbBulkTransfer]:
    """解析 pcapng 文件，提取所有 USB bulk transfer 载荷。

    参数:
        file_path: pcapng 文件路径。

    返回:
        按帧序号排列的 USB bulk transfer 列表。

    抛出:
        FileNotFoundError: 文件不存在。
        ValueError: 文件格式错误。
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"pcapng 文件不存在: {path}")

    logger.info("读取 pcapng 文件: %s (%d bytes)", path, path.stat().st_size)

    data = path.read_bytes()

    # 验证 pcapng magic
    if len(data) < 12:
        raise ValueError(f"文件太小，不是有效的 pcapng 文件: {path}")

    first_block_type = struct.unpack_from("<I", data, 0)[0]
    if first_block_type != _SHB_TYPE:
        raise ValueError(
            f"文件不以 SHB 块开头（期望 0x{_SHB_TYPE:08X}，"
            f"实际 0x{first_block_type:08X}）: {path}"
        )

    # 解析所有块
    blocks = _iter_blocks(data)

    # 提取 USB bulk transfer
    transfers: list[UsbBulkTransfer] = []
    frame_number = 0

    for block in blocks:
        if block.block_type == _EPB_TYPE:
            frame_number += 1
            transfer = _parse_epb_to_usb_bulk(block, frame_number)
            if transfer is not None:
                transfers.append(transfer)

    logger.info(
        "提取 USB bulk transfer: %d 帧（共 %d 个 EPB）",
        len(transfers),
        frame_number,
    )

    return transfers
