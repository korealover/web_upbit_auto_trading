from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectField, FloatField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, NumberRange
from app.models import User
from app.utils.tickers import get_ticker_choices

class LoginForm(FlaskForm):
    username = StringField('사용자명', validators=[DataRequired()])
    password = PasswordField('비밀번호', validators=[DataRequired()])
    remember_me = BooleanField('로그인 상태 유지')
    submit = SubmitField('로그인')


class RegistrationForm(FlaskForm):
    username = StringField('사용자명', validators=[DataRequired()])
    email = StringField('이메일', validators=[DataRequired(), Email()])
    password = PasswordField('비밀번호', validators=[DataRequired()])
    password2 = PasswordField('비밀번호 확인', validators=[DataRequired(), EqualTo('password')])
    upbit_access_key = StringField('업비트 ACCESS KEY', validators=[DataRequired()])
    upbit_secret_key = StringField('업비트 SECRET KEY', validators=[DataRequired()])

    submit = SubmitField('가입하기')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('이미 사용 중인 사용자명입니다.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('이미 사용 중인 이메일입니다.')


class ProfileForm(FlaskForm):
    username = StringField('사용자명', validators=[DataRequired()])
    email = StringField('이메일', validators=[DataRequired(), Email()])
    upbit_access_key = StringField('업비트 ACCESS KEY')
    upbit_secret_key = StringField('업비트 SECRET KEY')
    submit = SubmitField('프로필 업데이트')

    def __init__(self, original_username, original_email, *args, **kwargs):
        super(ProfileForm, self).__init__(*args, **kwargs)
        self.original_username = original_username
        self.original_email = original_email

    def validate_username(self, username):
        if username.data != self.original_username:
            user = User.query.filter_by(username=username.data).first()
            if user is not None:
                raise ValidationError('이미 사용 중인 사용자명입니다.')

    def validate_email(self, email):
        if email.data != self.original_email:
            user = User.query.filter_by(email=email.data).first()
            if user is not None:
                raise ValidationError('이미 사용 중인 이메일입니다.')


class TradingSettingsForm(FlaskForm):
    ticker = SelectField('코인 티커', validators=[DataRequired()], default='KRW-XRP')
    interval = SelectField('차트 간격', choices=[
        ('day', '일봉'), ('minute1', '1분'), ('minute3', '3분'),
        ('minute5', '5분'), ('minute10', '10분'), ('minute15', '15분'), ('minute30', '30분'),
        ('minute60', '60분'), ('minute240', '240분')
    ], default='minute5')

    # 전략 선택 - 새로운 전략들 추가
    strategy = SelectField('거래 전략', choices=[
        ('bollinger', '볼린저 밴드')
    ], default='bollinger')

    # 당분다 다른 전략은 주석 처리 ,
    # ('volatility', '변동성 돌파'),
    # ('rsi', 'RSI 전략'),
    # ('adaptive', '어댑티브 전략 (시장 상황 자동 감지)'),
    # ('ensemble', '앙상블 전략 (다중 전략 결합)')

    # 공통 설정
    buy_amount = FloatField('매수 금액 (원)', validators=[NumberRange(min=5000)], default=10000)
    min_cash = FloatField('최소 보유 현금량', validators=[NumberRange(min=0)], default=50000)
    sleep_time = IntegerField('거래 간격 (초)', validators=[NumberRange(min=10)], default=60)
    sell_portion = FloatField('매도 비율', validators=[NumberRange(min=0.1, max=1.0)], default=0.5)
    prevent_loss_sale = SelectField('손절 금지', choices=[('Y', '예'), ('N', '아니오')], default='Y')


    # 볼린저 밴드 전략 설정
    window = IntegerField('이동평균 기간', validators=[NumberRange(min=5)], default=20)
    multiplier = FloatField('볼린저 밴드 승수', validators=[NumberRange(min=0.1)], default=2.0)

    # 변동성 돌파 전략 설정
    k = FloatField('변동성 계수 (k)', validators=[NumberRange(min=0.1, max=1.0)], default=0.5)
    target_profit = FloatField('목표 수익률 (%)', validators=[NumberRange(min=0.1)], default=3.0)
    stop_loss = FloatField('손절 손실률 (%)', validators=[NumberRange(max=0)], default=-2.0)

    # RSI 전략 설정
    rsi_period = IntegerField('RSI 계산 기간', validators=[NumberRange(min=5, max=50)], default=14)
    rsi_oversold = FloatField('과매도 기준값', validators=[NumberRange(min=10, max=40)], default=30)
    rsi_overbought = FloatField('과매수 기준값', validators=[NumberRange(min=60, max=90)], default=70)
    rsi_timeframe = SelectField('RSI 차트 시간대', choices=[
        ('minute1', '1분봉'),
        ('minute3', '3분봉'),
        ('minute5', '5분봉'),
        ('minute10', '10분봉'),
        ('minute15', '15분봉'),
        ('minute30', '30분봉'),
        ('minute60', '60분봉'),
        ('minute240', '240분봉')
    ], default='minute15')

    # 앙상블 전략 가중치 설정
    ensemble_volatility_weight = FloatField('변동성 돌파 가중치', validators=[NumberRange(min=0, max=1)], default=0.3)
    ensemble_bollinger_weight = FloatField('볼린저 밴드 가중치', validators=[NumberRange(min=0, max=1)], default=0.4)
    ensemble_rsi_weight = FloatField('RSI 전략 가중치', validators=[NumberRange(min=0, max=1)], default=0.3)

    submit = SubmitField('자동 거래 봇 시작')

    def __init__(self, *args, **kwargs):
        super(TradingSettingsForm, self).__init__(*args, **kwargs)
        # 폼 초기화 시 티커 목록을 동적으로 설정
        self.ticker.choices = get_ticker_choices()


class FavoriteForm(FlaskForm):
    name = StringField('즐겨찾기 이름', validators=[DataRequired(message="이름을 입력해주세요.")])
    submit = SubmitField('저장')
