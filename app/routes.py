from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from app import app, db
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm, ProfileForm
from app.models import User, TradeRecord
from app.api.upbit_api import UpbitAPI
from app.bot.trading_bot import UpbitTradingBot
from app.strategy import create_strategy
from app.utils.logging_utils import setup_logger, get_logger_with_current_date
from app.utils.async_utils import AsyncHandler
from config import Config
import threading
import time
import html
import os
from datetime import datetime, timedelta

# 전역 변수
trading_bots = {}
async_handler = AsyncHandler(max_workers=5)
upbit_apis = {}  # 사용자별 API 객체 저장
logger = setup_logger('web', 'INFO', 7)


@app.route('/')
def index():
    return render_template('index.html')


# routes.py의 로그인 함수 수정
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

        # 계정 승인 확인 (관리자는 항상 로그인 가능)
        if not user.is_approved and not user.is_admin:
            flash('귀하의 계정은 아직 관리자 승인 대기 중입니다.', 'warning')
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


# routes.py의 회원가입 함수 수정
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
            upbit_secret_key=form.upbit_secret_key.data,
            is_approved=False  # 기본적으로 승인되지 않은 상태
        )

        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        # 승인 필요 메시지
        flash('회원가입이 완료되었습니다! 관리자 승인 후 로그인할 수 있습니다.', 'info')

        # 관리자에게 새 가입자 알림 (선택 사항)
        notify_admin_new_registration(user)

        return redirect(url_for('login'))
    return render_template('register.html', title='회원가입', form=form)


def notify_admin_new_registration(user):
    """관리자에게 새 회원가입 알림"""
    admins = User.query.filter_by(is_admin=True).all()
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    for admin in admins:
        logger.info(f"관리자 {admin.username}에게 새 회원 {user.username} 가입 알림")


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
    try:
        balance_info['cash'] = api.get_balance_cash()

        # 보유 코인 정보 조회 - pyupbit를 직접 사용
        try:
            all_balances = api.upbit.get_balances()  # pyupbit의 get_balances 메서드 사용
            balance_info['coins'] = []
            total_balance = balance_info['cash']

            if all_balances:
                for balance in all_balances:
                    if balance['currency'] != 'KRW' and float(balance['balance']) > 0:
                        ticker = f"KRW-{balance['currency']}"
                        try:
                            current_price = api.get_current_price(ticker)  # get_ticker를 get_current_price로 변경
                            coin_value = float(balance['balance']) * current_price
                            total_balance += coin_value

                            balance_info['coins'].append({
                                'ticker': ticker,
                                'balance': float(balance['balance']),
                                'value': coin_value,
                                'current_price': current_price
                            })
                        except Exception as e:
                            logger.warning(f"코인 {ticker} 가격 조회 실패: {str(e)}")

            balance_info['total_balance'] = total_balance

        except Exception as e:
            logger.warning(f"보유 코인 정보 조회 실패: {str(e)}")
            balance_info['total_balance'] = balance_info['cash']
            balance_info['coins'] = []

    except Exception as e:
        logger.error(f"잔고 정보 조회 실패: {str(e)}")
        balance_info['cash'] = 0
        balance_info['total_balance'] = 0
        balance_info['coins'] = []

    # 오늘의 거래 통계 계산
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_records = TradeRecord.query.filter_by(
        user_id=current_user.id
    ).filter(
        TradeRecord.timestamp >= today_start
    ).all()

    daily_stats = {}
    if today_records:
        # 총 거래 횟수
        daily_stats['total_trades'] = len(today_records)

        # 매수/매도 쌍으로 거래 완료된 것들의 성공 거래 계산
        successful_trades = 0
        total_profit = 0

        # 거래 기록을 티커별로 그룹화
        ticker_trades = {}
        for record in today_records:
            if record.ticker not in ticker_trades:
                ticker_trades[record.ticker] = {'buy': [], 'sell': []}

            if record.trade_type == 'BUY':
                ticker_trades[record.ticker]['buy'].append(record)
            else:
                ticker_trades[record.ticker]['sell'].append(record)

        # 각 티커별로 수익 계산
        for ticker, trades in ticker_trades.items():
            buy_trades = sorted(trades['buy'], key=lambda x: x.timestamp)
            sell_trades = sorted(trades['sell'], key=lambda x: x.timestamp)

            # 간단한 FIFO 방식으로 매수-매도 쌍 매칭
            buy_index = 0
            for sell_trade in sell_trades:
                if buy_index < len(buy_trades):
                    buy_trade = buy_trades[buy_index]

                    # 수익률 계산
                    profit_rate = ((float(sell_trade.price) - float(buy_trade.price)) / float(buy_trade.price)) * 100

                    if profit_rate > 0:
                        successful_trades += 1

                    total_profit += profit_rate
                    buy_index += 1

        # 승률 계산 (완료된 거래 쌍 기준)
        completed_trades = min(len([r for r in today_records if r.trade_type == 'BUY']),
                               len([r for r in today_records if r.trade_type == 'SELL']))

        daily_stats['successful_trades'] = successful_trades
        daily_stats['daily_return'] = total_profit / completed_trades if completed_trades > 0 else 0
        daily_stats['win_rate'] = (successful_trades / completed_trades * 100) if completed_trades > 0 else 0
    else:
        daily_stats = {
            'total_trades': 0,
            'successful_trades': 0,
            'daily_return': 0,
            'win_rate': 0
        }

    # 전략별 성과 계산
    strategy_performance = {}
    if today_records:
        strategy_stats = {}

        for record in today_records:
            strategy = record.strategy
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {'trades': 0, 'profit': 0, 'buy_records': [], 'sell_records': []}

            strategy_stats[strategy]['trades'] += 1

            if record.trade_type == 'BUY':
                strategy_stats[strategy]['buy_records'].append(record)
            else:
                strategy_stats[strategy]['sell_records'].append(record)

        # 각 전략별 수익률 계산
        for strategy, stats in strategy_stats.items():
            buy_records = sorted(stats['buy_records'], key=lambda x: x.timestamp)
            sell_records = sorted(stats['sell_records'], key=lambda x: x.timestamp)

            total_return = 0
            pair_count = 0

            # 매수-매도 쌍 매칭하여 수익률 계산
            for i in range(min(len(buy_records), len(sell_records))):
                buy_price = float(buy_records[i].price)
                sell_price = float(sell_records[i].price)
                return_rate = ((sell_price - buy_price) / buy_price) * 100
                total_return += return_rate
                pair_count += 1

            strategy_performance[strategy] = {
                'return': total_return / pair_count if pair_count > 0 else 0,
                'trades': stats['trades']
            }

    # 사용자별 봇 정보 가져오기
    user_bots = trading_bots.get(user_id, {})

    # 봇 정보에 마지막 신호 시간 추가
    for ticker, bot_info in user_bots.items():
        try:
            # 마지막 로그에서 신호 시간 추출 (선택적 구현)
            today = datetime.now().strftime('%Y%m%d')
            ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
            log_filename = f"{today}_{ticker_symbol}.log"
            log_path = os.path.join('logs', log_filename)

            if os.path.exists(log_path):
                last_lines = tail_file(log_path, 10)
                for line in reversed(last_lines):
                    if '매수' in line or '매도' in line or '신호' in line:
                        # 로그에서 시간 추출
                        parts = line.split(' - ')
                        if len(parts) >= 1:
                            bot_info['last_signal_time'] = parts[0]
                            break
                else:
                    bot_info['last_signal_time'] = None
            else:
                bot_info['last_signal_time'] = None

        except Exception as e:
            logger.warning(f"봇 {ticker} 마지막 신호 시간 조회 실패: {str(e)}")
            bot_info['last_signal_time'] = None

    # 거래 기록 조회 (최근 20개)
    trade_records = TradeRecord.query.filter_by(
        user_id=current_user.id
    ).order_by(
        TradeRecord.timestamp.desc()
    ).limit(20).all()

    return render_template('dashboard.html',
                           balance_info=balance_info,
                           trading_bots=user_bots,
                           trade_records=trade_records,
                           daily_stats=daily_stats,
                           strategy_performance=strategy_performance)

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


@app.route('/api/start_bot/<ticker>', methods=['POST'])
@login_required
def start_bot_route(ticker):
    # AJAX 요청으로 봇 시작
    data = request.json
    start_bot(ticker, data['strategy'], data)
    return jsonify({'status': 'success', 'message': f'{ticker} 봇이 시작되었습니다'})


@app.route('/api/stop_bot/<ticker>', methods=['POST'])
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
            get_logger_with_current_date(ticker, 'INFO', 7)
        )

    # 이미 실행 중인 봇이 있으면 종료
    if ticker in trading_bots[user_id]:
        trading_bots[user_id][ticker]['running'] = False
        # 봇이 종료될 시간 여유 주기
        time.sleep(1)

    # 사용자의 API 객체 사용
    upbit_api = upbit_apis[user_id]

    # 전략 생성
    logger = get_logger_with_current_date(ticker, 'INFO', 7)
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
            # 매 사이클마다 로거를 최신 날짜로 업데이트
            logger = get_logger_with_current_date(ticker, 'INFO', 7)
            bot.logger = logger  # 봇의 로거 업데이트

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





@app.route('/api/logs/<ticker>')
@login_required
def get_ticker_logs(ticker):
    # 로그 디렉토리
    log_dir = 'logs'

    # 오늘 날짜의 로그 파일 찾기
    today = datetime.now().strftime('%Y%m%d')
    ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
    log_filename = f"{today}_{ticker_symbol}.log"
    log_path = os.path.join(log_dir, log_filename)

    # 로그 파일이 없으면 빈 배열 반환
    if not os.path.exists(log_path):
        # 가장 최근 날짜의 로그 파일 찾기
        for days_back in range(1, 4):  # 1~3일 전까지 확인
            check_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
            old_log_filename = f"{check_date}_{ticker_symbol}.log"
            old_log_path = os.path.join(log_dir, old_log_filename)

            if os.path.exists(old_log_path):
                # 이전 날짜의 로그 파일 찾았을 때
                log_path = old_log_path
                break
        else:
            # 3일 이내에 로그 파일을 찾지 못한 경우
            return jsonify([])

    # 로그 파일의 마지막 100줄 효율적으로 읽기
    last_lines = tail_file(log_path, 100)

    # 로그 라인 파싱
    logs = []
    for line in last_lines:
        # 간단한 로그 파싱 (예: "2023-01-01 12:34:56 - INFO - 메시지")
        parts = line.strip().split(' - ', 2)
        if len(parts) >= 3:
            timestamp, level, message = parts
            # HTML 특수 문자 이스케이프 처리
            message = html.escape(message)
            logs.append({
                'timestamp': timestamp,
                'level': level,
                'message': message
            })

    return jsonify(logs)


@app.route('/api/logs')
@login_required
def get_all_logs():
    # 로그 디렉토리
    log_dir = 'logs'

    # 오늘 날짜의 기본 로그 파일 찾기
    today = datetime.now().strftime('%Y%m%d')
    log_filename = f"{today}_web.log"
    log_path = os.path.join(log_dir, log_filename)

    # 로그 파일이 없으면 빈 배열 반환
    if not os.path.exists(log_path):
        # 가장 최근 날짜의 로그 파일 찾기
        for days_back in range(1, 4):  # 1~3일 전까지 확인
            check_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
            old_log_filename = f"{check_date}_web.log"
            old_log_path = os.path.join(log_dir, old_log_filename)

            if os.path.exists(old_log_path):
                # 이전 날짜의 로그 파일 찾았을 때
                log_path = old_log_path
                break
        else:
            # 3일 이내에 로그 파일을 찾지 못한 경우
            return jsonify([])

    # 로그 파일의 마지막 100줄 효율적으로 읽기
    last_lines = tail_file(log_path, 100)

    # 로그 라인 파싱
    logs = []
    for line in last_lines:
        parts = line.strip().split(' - ', 2)
        if len(parts) >= 3:
            timestamp, level, message = parts
            # HTML 특수 문자 이스케이프 처리
            message = html.escape(message)
            logs.append({
                'timestamp': timestamp,
                'level': level,
                'message': message
            })

    return jsonify(logs)

@app.route('/api/active_tickers')
@login_required
def get_active_tickers():
    # 현재 사용자의 활성 티커 목록 반환
    user_id = current_user.id
    if user_id in trading_bots:
        tickers = list(trading_bots[user_id].keys())
        return jsonify(tickers)
    return jsonify([])


def tail_file(file_path, n=100):
    """파일의 마지막 n줄 읽기"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 파일 끝으로 이동
            f.seek(0, 2)
            # 파일 크기
            file_size = f.tell()

            # 빈 파일 체크
            if file_size == 0:
                return []

            # 파일 끝에서부터 읽기 시작
            lines = []
            chars_read = 0
            lines_found = 0

            # 파일 끝에서부터 역방향으로 읽기
            while lines_found < n and chars_read < file_size:
                # 한 번에 4KB씩 읽음
                chars_to_read = min(4096, file_size - chars_read)
                f.seek(file_size - chars_read - chars_to_read)
                data = f.read(chars_to_read)
                chars_read += chars_to_read

                # 줄 단위로 분리
                new_lines = data.split('\n')

                # 이전에 읽은 데이터와 합치기
                if lines and new_lines[-1]:
                    lines[0] = new_lines[-1] + lines[0]
                    new_lines = new_lines[:-1]

                # 새로운 줄 추가
                lines = new_lines + lines
                lines_found = len(lines)

            # 빈 줄 제거 및 최대 n줄 반환
            return [line for line in lines if line.strip()][-n:]
    except Exception as e:
        print(f"파일 읽기 오류: {str(e)}")
        return []


# routes.py에 관리자 페이지 추가
@app.route('/admin')
@login_required
def admin_panel():
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('index'))

    # 승인 대기 중인 사용자 목록
    pending_users = User.query.filter_by(is_approved=False).order_by(User.registered_on.desc()).all()

    # 승인된 사용자 목록
    approved_users = User.query.filter_by(is_approved=True).order_by(User.username).all()

    return render_template('admin/panel.html',
                           title='관리자 패널',
                           pending_users=pending_users,
                           approved_users=approved_users)


@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    user.is_approved = True
    user.approved_on = datetime.utcnow()
    user.approved_by = current_user.id
    db.session.commit()

    flash(f'사용자 {user.username}의 계정이 승인되었습니다.', 'success')

    # 사용자에게 승인 알림 (선택 사항)
    notify_user_approval(user)

    return redirect(url_for('admin_panel'))


@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_user(user_id):
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)

    # 사용자에게 거부 알림 (선택 사항)
    notify_user_rejection(user)

    # 사용자 삭제
    db.session.delete(user)
    db.session.commit()

    flash(f'사용자 {user.username}의 가입 요청이 거부되었습니다.', 'info')
    return redirect(url_for('admin_panel'))


def notify_user_approval(user):
    """사용자에게 계정 승인 알림"""
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    logger.info(f"사용자 {user.username}에게 계정 승인 알림")


def notify_user_rejection(user):
    """사용자에게 계정 거부 알림"""
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    logger.info(f"사용자 {user.username}에게 계정 거부 알림")

# 티커별 거래 기록 가져오는 API 엔드포인트 수정
@app.route('/api/trade_records')
@login_required
def get_trade_records():
    """오늘의 모든 거래 기록을 가져옵니다."""
    # 오늘 날짜의 시작 시간 계산 (00:00:00)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 오늘 거래 기록만 필터링
    records = TradeRecord.query.filter_by(
        user_id=current_user.id
    ).filter(
        TradeRecord.timestamp >= today_start
    ).order_by(
        TradeRecord.timestamp.desc()
    ).all()

    # JSON 응답용 데이터 변환
    result = []
    for record in records:
        result.append({
            'timestamp': record.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'ticker': record.ticker,
            'trade_type': record.trade_type,
            'price': float(record.price),
            'volume': float(record.volume),
            'amount': float(record.amount),
            'profit_loss': float(record.profit_loss) if record.profit_loss else None,
            'strategy': record.strategy
        })

    return jsonify(result)


@app.route('/api/trade_records/<ticker>')
@login_required
def get_ticker_trade_records(ticker):
    """특정 티커의 오늘 거래 기록을 가져옵니다."""
    # 오늘 날짜의 시작 시간 계산 (00:00:00)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 로그 기록 (디버깅 용도)
    logger.info(f"티커 {ticker}의 오늘 거래 기록 요청됨 (사용자 ID: {current_user.id})")

    # 특정 티커의 오늘 거래 기록만 필터링
    records = TradeRecord.query.filter_by(
        user_id=current_user.id,
        ticker=ticker
    ).filter(
        TradeRecord.timestamp >= today_start
    ).order_by(
        TradeRecord.timestamp.desc()
    ).all()

    # 조회된 레코드 수 로깅
    logger.info(f"티커 {ticker}의 거래 기록 {len(records)}개 조회됨")

    # JSON 응답용 데이터 변환
    result = []
    for record in records:
        result.append({
            'timestamp': record.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'ticker': record.ticker,
            'trade_type': record.trade_type,
            'price': float(record.price),
            'volume': float(record.volume),
            'amount': float(record.amount),
            'profit_loss': float(record.profit_loss) if record.profit_loss else None,
            'strategy': record.strategy
        })

    return jsonify(result)
