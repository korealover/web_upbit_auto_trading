import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
# .env 파일에서 환경 변수 로드
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
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
    # SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{os.path.join(basedir, "db", "app.db")}?timezone=Asia/Seoul'
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{os.environ.get('MYSQL_USER')}:{os.environ.get('MYSQL_PASSWORD')}@{os.environ.get('MYSQL_HOST')}:{os.environ.get('MYSQL_PORT')}/{os.environ.get('MYSQL_DATABASE')}?charset=utf8mb4"
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


