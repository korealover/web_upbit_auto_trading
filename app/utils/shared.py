from threading import Lock
import threading

# 공유 자원
trading_bots = {}
lock = Lock()