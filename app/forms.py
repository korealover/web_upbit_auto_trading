from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectField, FloatField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, NumberRange
from app.models import User

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
    ticker = StringField('코인 티커', validators=[DataRequired()], default='KRW-XLM')
    interval = SelectField('차트 간격', choices=[
        ('day', '일봉'), ('minute1', '1분'), ('minute3', '3분'),
        ('minute5', '5분'), ('minute10', '10분'), ('minute30', '30분'),
        ('minute60', '60분'), ('minute240', '4시간')
    ], default='day')
    strategy = SelectField('거래 전략', choices=[
        ('bollinger', '볼린저 밴드'),
        ('volatility', '변동성 돌파')
    ], default='bollinger')
    window = IntegerField('이동평균 기간', validators=[NumberRange(min=5)], default=20)
    multiplier = FloatField('볼린저 밴드 승수', validators=[NumberRange(min=0.1)], default=2.0)
    buy_amount = FloatField('매수 금액 (원)', validators=[NumberRange(min=5000)], default=10000)
    min_cash = FloatField('최소 보유 현금량', validators=[NumberRange(min=0)], default=10000)
    sleep_time = IntegerField('거래 간격 (초)', validators=[NumberRange(min=10)], default=30)
    k = FloatField('변동성 계수 (k)', validators=[NumberRange(min=0.1, max=1.0)], default=0.5)
    target_profit = FloatField('목표 수익률 (%)', validators=[NumberRange(min=0.1)], default=3.0)
    stop_loss = FloatField('손절 손실률 (%)', validators=[NumberRange(max=0)], default=-2.0)
    sell_portion = FloatField('매도 비율', validators=[NumberRange(min=0.1, max=1.0)], default=1.0)
    submit = SubmitField('설정 저장 및 봇 시작')