"""
Config Proxy — 设备代理配置模块。

严格按照 16.0-Config Proxy.pcapng 抓包还原的命令序列，
读取当前代理设置并配置新的 HTTP 代理。

命令序列（2 步）：
    1. settings get global http_proxy → 读取当前代理
    2. settings put global http_proxy host:port → 设置新代理

公共 API：
    - config_proxy(): 执行完整代理配置流程
    - ConfigProxyResult: 执行结果数据类
"""

from .config_proxy import config_proxy
from .models import ConfigProxyResult

__all__ = [
    "ConfigProxyResult",
    "config_proxy",
]
