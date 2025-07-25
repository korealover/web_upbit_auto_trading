from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from datetime import datetime
import pytz
from app.utils.encryption import encryption_service


def kst_now():
    """현재 한국 시간(KST)을 반환하는 함수"""
    kst = pytz.timezone('Asia/Seoul')
    return datetime.now(kst).replace(tzinfo=None)  # tzinfo 제거하여 naive datetime 반환


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    upbit_access_key = db.Column(db.Text)  # 암호화된 업비트 API 접근 키 (길이 증가)
    upbit_secret_key = db.Column(db.Text)  # 암호화된 업비트 API 비밀 키 (길이 증가)
    trade_records = db.relationship('TradeRecord', backref='user', lazy='dynamic')
    is_approved = db.Column(db.Boolean, default=False)  # 계정 승인 여부
    is_admin = db.Column(db.Boolean, default=False)  # 관리자 여부
    registered_on = db.Column(db.DateTime, default=kst_now)  # 가입 일시
    approved_on = db.Column(db.DateTime, nullable=True)  # 승인 일시
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # 승인한 관리자

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_upbit_keys(self, access_key, secret_key):
        """업비트 API 키 암호화 후 저장"""
        try:
            self.upbit_access_key = encryption_service.encrypt(access_key) if access_key else None
            self.upbit_secret_key = encryption_service.encrypt(secret_key) if secret_key else None
        except Exception as e:
            raise ValueError(f"API 키 암호화 실패: {str(e)}")

    def get_upbit_keys(self):
        """업비트 API 키 복호화 후 반환"""
        try:
            access_key = encryption_service.decrypt(self.upbit_access_key) if self.upbit_access_key else None
            secret_key = encryption_service.decrypt(self.upbit_secret_key) if self.upbit_secret_key else None
            return access_key, secret_key
        except Exception as e:
            raise ValueError(f"API 키 복호화 실패: {str(e)}")


@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))


class TradeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    ticker = db.Column(db.String(20), index=True)
    trade_type = db.Column(db.String(10))  # 'BUY' 또는 'SELL'
    price = db.Column(db.Float)
    volume = db.Column(db.Float)
    amount = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=kst_now)
    profit_loss = db.Column(db.Float, nullable=True)  # 매도의 경우 수익/손실률
    strategy = db.Column(db.String(20))  # 사용된 전략

    def __repr__(self):
        return f'<TradeRecord {self.ticker} {self.trade_type} {self.timestamp}>'


class TradingFavorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    ticker = db.Column(db.String(20), nullable=False)
    strategy = db.Column(db.String(50), nullable=False)
    interval = db.Column(db.String(10), nullable=False)
    buy_amount = db.Column(db.Float, nullable=False)
    min_cash = db.Column(db.Float, nullable=False)
    sleep_time = db.Column(db.Integer, nullable=False)
    sell_portion = db.Column(db.Float, nullable=False)
    prevent_loss_sale = db.Column(db.String(1), nullable=False, default='N')
    long_term_investment = db.Column(db.String(1), nullable=False, default='N')

    # 기존 볼린저 밴드 전략 설정
    window = db.Column(db.Integer, nullable=True)
    multiplier = db.Column(db.Float, nullable=True)

    # 비대칭 볼린저 밴드 전략 설정 (새로 추가)
    buy_multiplier = db.Column(db.Float, nullable=True)  # 매수용 승수
    sell_multiplier = db.Column(db.Float, nullable=True)  # 매도용 승수

    # 변동성 돌파 전략 설정
    k = db.Column(db.Float, nullable=True)
    target_profit = db.Column(db.Float, nullable=True)
    stop_loss = db.Column(db.Float, nullable=True)

    # RSI 전략 설정
    rsi_period = db.Column(db.Integer, nullable=True)
    rsi_oversold = db.Column(db.Float, nullable=True)
    rsi_overbought = db.Column(db.Float, nullable=True)
    rsi_timeframe = db.Column(db.String(10), nullable=True)

    # 앙상블 전략 설정
    ensemble_volatility_weight = db.Column(db.Float, nullable=True)
    ensemble_bollinger_weight = db.Column(db.Float, nullable=True)
    ensemble_rsi_weight = db.Column(db.Float, nullable=True)

    start_yn = db.Column(db.String(1), nullable=False, default='N')
    created_at = db.Column(db.DateTime, default=kst_now)
    updated_at = db.Column(db.DateTime, default=kst_now, onupdate=kst_now)

    def __repr__(self):
        return f'<TradingFavorite {self.name}>'

    def to_dict(self):
        return {
            'ticker': self.ticker,
            'strategy': self.strategy,
            'interval': self.interval,
            'buy_amount': self.buy_amount,
            'min_cash': self.min_cash,
            'sleep_time': self.sleep_time,
            'sell_portion': self.sell_portion,
            'prevent_loss_sale': self.prevent_loss_sale,
            'long_term_investment': self.long_term_investment,
            'window': self.window,
            'multiplier': self.multiplier,
            # 비대칭 볼린저 밴드 필드 추가
            'buy_multiplier': self.buy_multiplier,
            'sell_multiplier': self.sell_multiplier,
            'k': self.k,
            'target_profit': self.target_profit,
            'stop_loss': self.stop_loss,
            'rsi_period': self.rsi_period,
            'rsi_oversold': self.rsi_oversold,
            'rsi_overbought': self.rsi_overbought,
            'rsi_timeframe': self.rsi_timeframe,
            'ensemble_volatility_weight': self.ensemble_volatility_weight,
            'ensemble_bollinger_weight': self.ensemble_bollinger_weight,
            'ensemble_rsi_weight': self.ensemble_rsi_weight,
            'start_yn': self.start_yn,
        }