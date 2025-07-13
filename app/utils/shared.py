from threading import Lock

# 공유 자원
trading_bots = {}
scheduled_bots = {}  # {user_id: {ticker: {'job_id': str, 'bot': obj, 'info': dict}}}
lock = Lock()