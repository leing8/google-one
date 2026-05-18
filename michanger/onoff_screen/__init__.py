"""
ONOFF Screen — 屏幕开关切换模块。

严格按照 19.0-ONOFF Screen.pcapng 抓包还原，
通过 input keyevent KEYCODE_POWER 切换屏幕开关状态。

命令序列（1 步）：
    1. input keyevent KEYCODE_POWER → 切换屏幕（亮屏 ↔ 熄屏）

公共 API：
    - onoff_screen(): 执行屏幕开关切换
    - OnOffScreenResult: 执行结果数据类
"""

from .models import OnOffScreenResult
from .onoff_screen import onoff_screen

__all__ = [
    "OnOffScreenResult",
    "onoff_screen",
]
