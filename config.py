import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
# .env 파일에서 환경 변수 로드
load_dotenv()

class Config:
    UPBIT_ACCESS_KEY = os.environ.get("UPBIT_ACCESS_KEY")
    UPBIT_SECRET_KEY = os.environ.get("UPBIT_SECRET_KEY")
    UPBIT_SERVER_URL = os.environ.get("UPBIT_SERVER_URL")

    # 캐싱 설정
    CACHE_DURATION_PRICE = int(os.environ.get("CACHE_DURATION_PRICE", "1"))
    CACHE_DURATION_BALANCE = int(os.environ.get("CACHE_DURATION_BALANCE", "5"))
    CACHE_DURATION_OHLCV = int(os.environ.get("CACHE_DURATION_OHLCV", "60"))
    CACHE_DURATION_PRICE_AVG = int(os.environ.get("CACHE_DURATION_PRICE_AVG", "10"))

    # 텔레그램 설정
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    TELEGRAM_CHAT_ID_PERSONAL = os.environ.get("TELEGRAM_CHAT_ID_PERSONAL")
    TELEGRAM_NOTIFICATIONS_ENABLED = os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED", "False").lower() == "true"

    # DB 설정
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{os.path.join(basedir, "db", "app.db")}?timezone=Asia/Seoul'
    # SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{os.environ.get('MYSQL_USER')}:{os.environ.get('MYSQL_PASSWORD')}@{os.environ.get('MYSQL_HOST')}:{os.environ.get('MYSQL_PORT')}/{os.environ.get('MYSQL_DATABASE')}?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},  # SQLite 용
        'echo_pool': True
    }

    # 시간대 설정
    TIMEZONE = 'Asia/Seoul'

    # SocketIO 설정
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    SOCKETIO_ASYNC_MODE = 'threading'
    SOCKETIO_PING_TIMEOUT = 60
    SOCKETIO_PING_INTERVAL = 25

    # 스레드 모니터링 설정
    THREAD_MONITOR_ENABLED = os.environ.get('THREAD_MONITOR_ENABLED', 'True').lower() == 'true'
    THREAD_MONITOR_MAX_HISTORY = int(os.environ.get('THREAD_MONITOR_MAX_HISTORY', '1000'))
    THREAD_MONITOR_ALERT_THRESHOLDS = {
        'max_threads': int(os.environ.get('MAX_THREADS_THRESHOLD', '50')),
        'max_cpu': float(os.environ.get('MAX_CPU_THRESHOLD', '80.0')),
        'max_memory': float(os.environ.get('MAX_MEMORY_THRESHOLD', '500.0')),
        'max_thread_age': int(os.environ.get('MAX_THREAD_AGE_THRESHOLD', '3600'))
    }

    # 스레드 풀 설정
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '5'))
    THREAD_NAME_PREFIX = os.environ.get('THREAD_NAME_PREFIX', 'AsyncWorker')

    # MCP 서버 관련 설정 추가
    MCP_SERVER_HOST = os.environ.get('MCP_SERVER_HOST', '0.0.0.0')
    MCP_SERVER_PORT = int(os.environ.get('MCP_SERVER_PORT', 5001))
    MCP_SECRET_KEY = os.environ.get('MCP_SECRET_KEY', SECRET_KEY)  # 기존 SECRET_KEY 재사용
    MCP_AUTH_TOKEN = os.environ.get('MCP_AUTH_TOKEN', 'mcp-auth-token-2025')



