import os
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
    UPBIT_SERVER_URL = os.environ.get("UPBIT_SERVER_URL")

    # 캐싱 설정
    CACHE_DURATION_PRICE = int(os.environ.get("CACHE_DURATION_PRICE", "1"))
    CACHE_DURATION_BALANCE = int(os.environ.get("CACHE_DURATION_BALANCE", "5"))
    CACHE_DURATION_OHLCV = int(os.environ.get("CACHE_DURATION_OHLCV", "60"))
    CACHE_DURATION_PRICE_AVG = int(os.environ.get("CACHE_DURATION_PRICE_AVG", "10"))

    # 텔레그램 설정
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    TELEGRAM_NOTIFICATIONS_ENABLED = os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED", "False").lower() == "true"
    
    # DB 설정
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{os.path.join(basedir, "db", "app.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
