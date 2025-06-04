from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from app import app, db
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm, ProfileForm
from app.models import User, TradeRecord
from app.api.upbit_api import UpbitAPI
from app.bot.trading_bot import UpbitTradingBot
from app.strategy import create_strategy
from app.utils.logging_utils import setup_logger
from app.utils.async_utils import AsyncHandler
from config import Config
import threading
import time

# 전역 변수
trading_bots = {}
async_handler = AsyncHandler(max_workers=5)
upbit_apis = {}  # 사용자별 API 객체 저장
logger = setup_logger('web', 'INFO', 7)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('유효하지 않은 사용자명 또는 비밀번호입니다.', 'danger')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('index')
        flash('로그인되었습니다!', 'success')
        return redirect(next_page)
    return render_template('login.html', title='로그인', form=form)


@app.route('/logout')
def logout():
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            upbit_access_key=form.upbit_access_key.data,
            upbit_secret_key=form.upbit_secret_key.data
        )

        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('회원가입이 완료되었습니다! 이제 로그인할 수 있습니다.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='회원가입', form=form)


@app.route('/dashboard')
@login_required
def dashboard():
    # 현재 사용자의 API 객체 확인
    user_id = current_user.id
    if user_id not in upbit_apis:
        # 사용자의 API 키로 새 API 객체 생성
        upbit_apis[user_id] = UpbitAPI(
            current_user.upbit_access_key,
            current_user.upbit_secret_key,
            async_handler,
            setup_logger('web', 'INFO', 7)
        )

    # 현재 사용자의 API 객체 사용
    api = upbit_apis[user_id]

    # 잔고 정보 조회
    balance_info = {}
    balance_info['cash'] = api.get_balance_cash()

    # 사용자별 봇 정보 가져오기
    user_bots = trading_bots.get(user_id, {})

    # 거래 기록 조회
    trade_records = TradeRecord.query.filter_by(user_id=current_user.id).order_by(TradeRecord.timestamp.desc()).limit(20).all()

    return render_template('dashboard.html', balance_info=balance_info, trading_bots=user_bots, trade_records=trade_records)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = TradingSettingsForm()
    if form.validate_on_submit():
        # 폼에서 설정값 추출
        ticker = form.ticker.data
        strategy_name = form.strategy.data
        # 기타 설정값들...

        # 봇 설정 및 시작
        start_bot(ticker, strategy_name, form)
        flash(f'{ticker} 봇이 시작되었습니다!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('settings.html', form=form)


@app.route('/start_bot/<ticker>', methods=['POST'])
@login_required
def start_bot_route(ticker):
    # AJAX 요청으로 봇 시작
    data = request.json
    start_bot(ticker, data['strategy'], data)
    return jsonify({'status': 'success', 'message': f'{ticker} 봇이 시작되었습니다'})


@app.route('/stop_bot/<ticker>', methods=['POST'])
@login_required
def stop_bot_route(ticker):
    user_id = current_user.id

    if user_id in trading_bots and ticker in trading_bots[user_id]:
        # 봇 종료 로직
        trading_bots[user_id][ticker]['running'] = False
        del trading_bots[user_id][ticker]
        return jsonify({'status': 'success', 'message': f'{ticker} 봇이 종료되었습니다'})
    return jsonify({'status': 'error', 'message': '해당 봇을 찾을 수 없습니다'})


def start_bot(ticker, strategy_name, settings):
    user_id = current_user.id

    # 사용자별 봇 관리 구조 설정
    if user_id not in trading_bots:
        trading_bots[user_id] = {}

    # 사용자별 API 객체 설정
    if user_id not in upbit_apis:
        upbit_apis[user_id] = UpbitAPI(
            current_user.upbit_access_key,
            current_user.upbit_secret_key,
            async_handler,
            setup_logger(ticker, 'INFO', 7)
        )

    # 이미 실행 중인 봇이 있으면 종료
    if ticker in trading_bots[user_id]:
        trading_bots[user_id][ticker]['running'] = False
        # 봇이 종료될 시간 여유 주기
        time.sleep(1)

    # 사용자의 API 객체 사용
    upbit_api = upbit_apis[user_id]

    # 전략 생성
    logger = setup_logger(ticker, 'INFO', 7)
    strategy = create_strategy(strategy_name, upbit_api, logger)

    # settings 객체에 user_id 추가
    if hasattr(settings, '__dict__'):
        settings.user_id = user_id
        logger.info(f"settings 객체에 user_id 추가: {user_id} (속성 설정)")
    elif isinstance(settings, dict):
        settings['user_id'] = user_id
        logger.info(f"settings 딕셔너리에 user_id 추가: {user_id}")
    else:
        logger.warning(f"알 수 없는 settings 유형: {type(settings)}")

    # 봇 생성
    bot = UpbitTradingBot(settings, upbit_api, strategy, logger)

    # 봇 정보 저장
    trading_bots[user_id][ticker] = {
        'bot': bot,
        'strategy': strategy_name,
        'settings': settings,
        'running': True
    }

    # 봇 실행 스레드 시작
    thread = threading.Thread(target=run_bot_thread, args=(user_id, ticker))
    thread.daemon = True
    thread.start()


def run_bot_thread(user_id, ticker):
    bot_info = trading_bots[user_id][ticker]
    bot = bot_info['bot']

    try:
        cycle_count = 0
        while bot_info['running']:
            cycle_count += 1
            logger = bot.logger
            logger.info(f"{ticker} 사이클 #{cycle_count} 시작")

            # 거래 사이클 실행
            bot.run_cycle()

            # 설정된 시간만큼 대기
            if hasattr(bot_info['settings'], 'sleep_time'):
                sleep_time = bot_info['settings'].sleep_time.data
            # AJAX 요청으로부터 받은 데이터인 경우 (딕셔너리)
            elif isinstance(bot_info['settings'], dict) and 'sleep_time' in bot_info['settings']:
                sleep_time = bot_info['settings']['sleep_time']
            else:
                sleep_time = 30  # 기본값

            time.sleep(sleep_time)

    except Exception as e:
        logger.error(f"{ticker} 봇 실행 중 오류 발생: {str(e)}", exc_info=True)
        bot_info['running'] = False


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(current_user.username, current_user.email)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.email = form.email.data

        # API 키가 입력된 경우에만 업데이트
        if form.upbit_access_key.data:
            current_user.upbit_access_key = form.upbit_access_key.data
        if form.upbit_secret_key.data:
            current_user.upbit_secret_key = form.upbit_secret_key.data

        db.session.commit()

        # API 객체 재생성 (API 키가 변경된 경우)
        if form.upbit_access_key.data or form.upbit_secret_key.data:
            user_id = current_user.id
            if user_id in upbit_apis:
                del upbit_apis[user_id]  # 기존 API 객체 제거

            # 만약 사용자의 봇이 실행 중이었다면 중지
            if user_id in trading_bots:
                for ticker in list(trading_bots[user_id].keys()):
                    trading_bots[user_id][ticker]['running'] = False
                trading_bots[user_id] = {}

        flash('프로필이 업데이트되었습니다.', 'success')
        return redirect(url_for('profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.email.data = current_user.email
        # API 키는 보안상 폼에 미리 채우지 않음

    return render_template('profile.html', title='프로필', form=form)


@app.route('/validate_api_keys', methods=['POST'])
@login_required
def validate_api_keys():
    data = request.json
    access_key = data.get('access_key')
    secret_key = data.get('secret_key')

    try:
        # 임시 API 객체 생성하여 잔고 조회 시도
        from pyupbit import Upbit
        temp_upbit = Upbit(access_key, secret_key)
        balance = temp_upbit.get_balance("KRW")

        if balance is not None:
            return jsonify({'valid': True, 'message': '업비트 API 키가 유효합니다.'})
        else:
            return jsonify({'valid': False, 'message': 'API 키로 잔고를 조회할 수 없습니다.'})
    except Exception as e:
        return jsonify({'valid': False, 'message': f'API 키 검증 오류: {str(e)}'})