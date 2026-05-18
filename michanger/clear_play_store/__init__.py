"""
Clear Google Play Store — 清除 Play Store 数据模块。

严格按照 18.0-Clear Google Play Store.pcapng 抓包还原，
使用 pm clear com.android.vending 清除 Play Store 数据。

命令序列（1 步）：
    1. pm clear com.android.vending → "Success"

公共 API：
    - clear_play_store(): 执行 Play Store 数据清除
    - ClearPlayStoreResult: 执行结果数据类
"""

from .clear_play_store import clear_play_store
from .models import ClearPlayStoreResult

__all__ = [
    "ClearPlayStoreResult",
    "clear_play_store",
]
