"""
Clean All Proxy — 清除设备全局代理模块。

严格按照 17.0-Clean All Proxy.pcapng 抓包还原的命令序列，
使用 settings put global http_proxy :0 清除全局代理。

与 config_proxy（16.0 pcapng）形成完整的代理生命周期：
    - config_proxy:    settings put global http_proxy host:port → 设置代理
    - clean_all_proxy: settings put global http_proxy :0         → 清除代理

命令序列（1 步）：
    1. settings put global http_proxy :0

公共 API：
    - clean_all_proxy(): 执行代理清除
    - CleanProxyResult: 执行结果数据类
"""

from .clean_all_proxy import clean_all_proxy
from .models import CleanProxyResult

__all__ = [
    "CleanProxyResult",
    "clean_all_proxy",
]
