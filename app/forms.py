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
    # buy_amount = FloatField('매수 금액 (원)', validators=[NumberRange(min=5000)], default=10000)
    buy_amount = SelectField('매수 금액 (원)', choices=[
        (5000.0, '5,000원'), (10000.0, '10,000원'), (20000.0, '20,000원'), (30000.0, '30,000원'), (40000.0, '40,000원'),
        (50000.0, '50,000원'), (60000.0, '60,000원'), (70000.0, '70,000원'), (80000.0, '80,000원'), (90000.0, '90,000원'), (100000.0, '100,000원')
    ], default=10000.0)
    # min_cash = FloatField('최소 보유 현금량', validators=[NumberRange(min=0)], default=50000)
    min_cash = SelectField('최소 보유 현금량', choices=[
        (0.0, '0원'), (500.0, '500원'), (5000.0, '5,000원'), (10000.0, '10,000원'), (30000.0, '30,000원'), (50000.0, '50,000원'), (100000.0, '100,000원'), (200000.0, '200,000원'), (300000.0, '300,000원'), (400000.0, '400,000원')
        , (500000.0, '500,000원'), (600000.0, '600,000원'), (700000.0, '700,000원'), (800000.0, '800,000원'), (900000.0, '900,000원'), (1000000.0, '1,000,000원')
    ], default=50000.0)
    # sleep_time = IntegerField('거래 간격 (초)', validators=[NumberRange(min=10)], default=60)
    sleep_time = SelectField('거래 간격 (초)', choices=[
        (30, '30초'), (60, '60초'), (100, '100초'), (120, '2분'), (180, '3분'), (300, '5분')
    ], default=60)
    sell_portion = SelectField('매도 비율', choices=[
        (0.1, '10%'), (0.2, '20%'), (0.3, '30%'), (0.4, '40%'), (0.5, '50%'),
        (0.6, '60%'), (0.7, '70%'), (0.8, '80%'), (0.9, '90%'), (1.0, '100%')
    ], default=0.5)
    prevent_loss_sale = SelectField('손절 금지', choices=[('Y', '예'), ('N', '아니오')], default='Y')
    long_term_investment = SelectField('장기 투자', choices=[('Y', '예'), ('N', '아니오')], default='N')


    # 볼린저 밴드 전략 설정
    window = IntegerField('이동평균 기간', validators=[NumberRange(min=5)], default=20)
    multiplier = SelectField('볼린저 밴드 승수', choices=[
        (1.0, '1.0'), (2.0, '2.0(기본)'), (3.0, '3.0'), (4.0, '4.0'), (5.0, '5.0')
    ], default=2.0)

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
    start_yn = BooleanField('서비스 재시작 시 자동거래 시작', default=False)
    submit = SubmitField('저장')
