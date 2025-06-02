from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from app import app, db
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm
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
upbit_api = None
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
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('회원가입이 완료되었습니다! 이제 로그인할 수 있습니다.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='회원가입', form=form)


@app.route('/dashboard')
@login_required
def dashboard():
    # 현재 실행 중인 봇 정보와 잔고 정보 표시
    balance_info = {}
    if upbit_api:
        balance_info['cash'] = upbit_api.get_balance_cash()

    trading_bots = {}
    # 거래 기록 조회 (최근 20개)
    trade_records = TradeRecord.query.filter_by(user_id=current_user.id).order_by(TradeRecord.timestamp.desc()).limit(20).all()

    return render_template('dashboard.html', balance_info=balance_info, trading_bots=trading_bots, trade_records=trade_records)


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
    if ticker in trading_bots:
        # 봇 종료 로직
        trading_bots[ticker]['running'] = False
        del trading_bots[ticker]
        return jsonify({'status': 'success', 'message': f'{ticker} 봇이 종료되었습니다'})
    return jsonify({'status': 'error', 'message': '해당 봇을 찾을 수 없습니다'})


def start_bot(ticker, strategy_name, settings):
    global upbit_api

    # 이미 실행 중인 봇이 있으면 종료
    if ticker in trading_bots:
        trading_bots[ticker]['running'] = False
        # 봇이 종료될 시간 여유 주기
        time.sleep(1)

    # API 객체가 없으면 초기화
    if upbit_api is None:
        upbit_api = UpbitAPI(Config.UPBIT_ACCESS_KEY, Config.UPBIT_SECRET_KEY, async_handler, logger)

    # 전략 생성
    strategy = create_strategy(strategy_name, upbit_api, logger)

    # settings 객체에 user_id 추가
    if hasattr(settings, 'user_id'):
        settings.user_id = current_user.id
    elif isinstance(settings, dict):
        settings['user_id'] = current_user.id

    # 봇 생성 (여기서는 args 대신 settings 객체 사용)
    bot = UpbitTradingBot(settings, upbit_api, strategy, logger)

    # 봇 실행 스레드 생성
    trading_bots[ticker] = {
        'bot': bot,
        'strategy': strategy_name,
        'settings': settings,
        'running': True
    }

    thread = threading.Thread(target=run_bot_thread, args=(ticker,))
    thread.daemon = True
    thread.start()


def run_bot_thread(ticker):
    bot_info = trading_bots[ticker]
    bot = bot_info['bot']

    try:
        cycle_count = 0
        while bot_info['running']:
            cycle_count += 1
            logger.info(f"{ticker} 사이클 #{cycle_count} 시작")

            # 거래 사이클 실행
            bot.run_cycle()

            # 설정된 시간만큼 대기
            # TradingSettingsForm 객체에서 sleep_time 필드의 data 속성에 접근
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