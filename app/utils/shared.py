from threading import Lock

# 공유 자원
trading_bots = {}
lock = Lock()