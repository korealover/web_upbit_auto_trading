from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_user, logout_user, current_user, login_required
from flask_socketio import emit
from app import db, socketio
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm, ProfileForm, FavoriteForm
from app.models import User, TradeRecord, kst_now, TradingFavorite
from app.api.upbit_api import UpbitAPI
from app.strategy import create_strategy
from app.utils.logging_utils import setup_logger, get_logger_with_current_date
from app.utils.async_utils import AsyncHandler
from app.utils.shared import trading_bots, lock
from app.utils.thread_controller import thread_controller, stop_thread, stop_user_threads, stop_all_threads, emergency_stop, get_thread_status
from app.bot.trading_bot import UpbitTradingBot
import time
import html
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from app.utils.thread_monitor import thread_monitor
from config import Config


# 환경 변수에서 Thread Pool 설정 로드
thread_pool = ThreadPoolExecutor(
    max_workers=Config.MAX_WORKERS,
    thread_name_prefix=Config.THREAD_NAME_PREFIX
)

# Blueprint 생성
bp = Blueprint('main', __name__)

# 전역 변수
async_handler = AsyncHandler(max_workers=5)
upbit_apis = {}  # 사용자별 API 객체 저장
logger = setup_logger('web', 'INFO', 7)

# WebSocket 관련 전역 변수
websocket_clients = {}  # 클라이언트별 구독 정보 저장
log_subscribers = {}  # 로그 구독자 관리


@bp.route('/')
def index():
    return render_template('index.html')


# routes.py의 로그인 함수 수정
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('유효하지 않은 사용자명 또는 비밀번호입니다.', 'danger')
            return redirect(url_for('main.login'))

        # 계정 승인 확인 (관리자는 항상 로그인 가능)
        if not user.is_approved and not user.is_admin:
            flash('귀하의 계정은 아직 관리자 승인 대기 중입니다.', 'warning')
            return redirect(url_for('main.login'))

        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('main.index')
        flash('로그인되었습니다!', 'success')
        return redirect(next_page)
    return render_template('login.html', title='로그인', form=form)


@bp.route('/logout')
def logout():
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('main.index'))


# routes.py의 회원가입 함수 수정
@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
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

        return redirect(url_for('main.login'))
    return render_template('register.html', title='회원가입', form=form)


def notify_admin_new_registration(user):
    """관리자에게 새 회원가입 알림"""
    admins = User.query.filter_by(is_admin=True).all()
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    for admin in admins:
        logger.info(f"관리자 {admin.username}에게 새 회원 {user.username} 가입 알림")


@bp.route('/dashboard')
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
        if balance_info['cash'] is None:
            balance_info['cash'] = 0

        # 보유 코인 정보 조회 - pyupbit를 직접 사용
        try:
            all_balances = api.upbit.get_balances()  # pyupbit의 get_balances 메서드 사용
            balance_info['coins'] = []
            total_balance = balance_info['cash']

            if all_balances:
                # print(all_balances)
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
                                'avg_buy_price': float(balance['avg_buy_price']),
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


# @bp.route('/settings', methods=['GET', 'POST'])
# @login_required
# def settings():
#     form = TradingSettingsForm()
#     if form.validate_on_submit():
#         # 폼에서 설정값 추출
#         ticker = form.ticker.data
#         strategy_name = form.strategy.data
#         # 기타 설정값들...
#
#         # 봇 설정 및 시작
#         start_bot(ticker, strategy_name, form)
#         flash(f'{ticker} 봇이 시작되었습니다!', 'success')
#         return redirect(url_for('main.dashboard'))
#
#     return render_template('settings.html', form=form)


@bp.route('/api/start_bot/<ticker>', methods=['POST'])
@login_required
def start_bot_route(ticker):
    # AJAX 요청으로 봇 시작
    data = request.json
    start_bot(ticker, data['strategy'], data)
    return jsonify({'status': 'success', 'message': f'{ticker} 봇이 시작되었습니다'})


@bp.route('/api/stop_bot/<ticker>', methods=['POST'])
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

    with lock:
        if user_id not in trading_bots:
            trading_bots[user_id] = {}
        if user_id not in upbit_apis:
            upbit_apis[user_id] = UpbitAPI(
                current_user.upbit_access_key,
                current_user.upbit_secret_key,
                async_handler,
                get_logger_with_current_date(ticker, 'INFO', 7)
            )
        if ticker in trading_bots[user_id]:
            trading_bots[user_id][ticker]['running'] = False
            time.sleep(1)

    upbit_api = upbit_apis[user_id]
    logger = get_logger_with_current_date(ticker, 'INFO', 7)
    strategy = create_strategy(strategy_name, upbit_api, logger)

    if hasattr(settings, '__dict__'):
        settings.user_id = user_id
        logger.info(f"settings 객체에 user_id 추가: {user_id} (속성 설정)")
    elif isinstance(settings, dict):
        settings['user_id'] = user_id
        logger.info(f"settings 딕셔너리에 user_id 추가: {user_id}")
    else:
        logger.warning(f"알 수 없는 settings 유형: {type(settings)}")

    websocket_logger = WebSocketLogger(ticker, user_id)
    bot = UpbitTradingBot(settings, upbit_api, strategy, websocket_logger, current_user.username)

    with lock:
        trading_bots[user_id][ticker] = {
            'bot': bot,
            'strategy': strategy_name,
            'settings': settings,
            'running': True,
            'interval_label': get_selected_label(settings.interval),
            'username': current_user.username,
            'thread_id': None,  # 초기값, 나중에 업데이트
            'start_time': datetime.now()

        }

    # 스레드 풀에 작업 제출하고 Future 객체 반환
    future = thread_pool.submit(run_bot_process, user_id, ticker)

    # thread_id 업데이트 (Future 객체의 내부 스레드 ID 사용)
    with lock:
        trading_bots[user_id][ticker]['thread_id'] = id(future)  # 또는 다른 고유 식별자


# 선택 필드에서 라벨을 가져오기
def get_selected_label(form_field):
    for value, label in form_field.choices:
        if value == form_field.data:
            return label
    return None

def run_bot_process(user_id, ticker):
    """봇 실행 프로세스 (run_bot_thread에서 이름 변경)"""
    try:
        bot_info = trading_bots[user_id][ticker]
        bot = bot_info['bot']
        cycle_count = 0
        while bot_info['running']:
            cycle_count += 1
            # 매 사이클마다 로거를 최신 날짜로 업데이트
            websocket_logger = WebSocketLogger(ticker, user_id)
            bot.logger = websocket_logger  # 봇의 로거 업데이트

            websocket_logger.info(f"{ticker} 사이클 #{cycle_count} 시작")

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
        websocket_logger = WebSocketLogger(ticker, user_id)
        websocket_logger.error(f"{ticker} 봇 실행 중 오류 발생: {str(e)}", exc_info=True)
        bot_info['running'] = False

    finally:
        websocket_logger = WebSocketLogger(ticker, user_id)
        # 종료 시 전역 상태에서 제거
        with lock:
            if user_id in trading_bots and ticker in trading_bots[user_id]:
                del trading_bots[user_id][ticker]
                websocket_logger.info(f"트레이딩 봇 종료: {ticker}, User ID: {user_id}")


@bp.route('/profile', methods=['GET', 'POST'])
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
        return redirect(url_for('main.profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.email.data = current_user.email
        # API 키는 보안상 폼에 미리 채우지 않음

    return render_template('profile.html', title='프로필', form=form)


@bp.route('/validate_api_keys', methods=['POST'])
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


# ===== WebSocket 이벤트 핸들러를 별도 파일로 이동 =====
# 이 부분들은 websocket_handlers.py에서 처리됩니다.
# ===== WebSocket 로거 클래스 =====
class WebSocketLogger:
    """WebSocket을 통해 실시간 로그를 전송하는 로거"""

    def __init__(self, ticker, user_id):
        self.ticker = ticker
        self.user_id = str(user_id)
        self.file_logger = get_logger_with_current_date(ticker, 'INFO', 7)

    def _emit_log(self, level, message):
        """WebSocket으로 로그 전송"""
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'level': level,
            'message': message,
            'raw_timestamp': datetime.now().isoformat(),
            'ticker': self.ticker,
            'user_id': self.user_id
        }

        # 파일에도 로그 기록
        getattr(self.file_logger, level.lower(), self.file_logger.info)(message)

        # WebSocket 구독자들에게 전송
        self._send_to_subscribers(log_entry)

    def _send_to_subscribers(self, log_entry):
        """구독자들에게 로그 전송"""
        try:
            # websocket_handlers의 active_connections를 사용하여 특정 사용자에게만 전송
            from app.websocket_handlers import active_connections

            # 해당 사용자의 활성 세션들을 찾아서 전송
            for session_id, conn_info in active_connections.items():
                if str(conn_info['user_id']) == self.user_id:
                    # 해당 사용자가 구독 중인 티커와 일치하거나 전체 로그를 구독 중인 경우
                    subscribed_ticker = conn_info.get('subscribed_ticker', '')
                    if not subscribed_ticker or subscribed_ticker == self.ticker:
                        # socketio 대신 websocket_handlers에서 직접 emit
                        try:
                            socketio.emit('new_log', log_entry, room=session_id)
                        except Exception as emit_error:
                            self.file_logger.debug(f"세션 {session_id}로 로그 전송 실패: {str(emit_error)}")

        except ImportError:
            # active_connections 가져오기 실패 시 기본 파일 로깅만 수행
            self.file_logger.debug("active_connections를 가져올 수 없음. 파일 로깅만 수행.")
        except Exception as e:
            # WebSocket 전송 실패 시 파일 로거에만 기록
            self.file_logger.debug(f"WebSocket 로그 전송 실패: {str(e)}")

    def info(self, message):
        self._emit_log('INFO', message)

    def warning(self, message):
        self._emit_log('WARNING', message)

    def error(self, message, exc_info=False):
        if exc_info:
            import traceback
            message += f"\n{traceback.format_exc()}"
        self._emit_log('ERROR', message)

    def debug(self, message):
        self._emit_log('DEBUG', message)


# ===== 기존 REST API 엔드포인트들 유지 =====
@bp.route('/api/logs/<ticker>')
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


@bp.route('/api/logs')
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


@bp.route('/api/active_tickers')
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
@bp.route('/admin')
@login_required
def admin_panel():
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('main.index'))

    # 승인 대기 중인 사용자 목록
    pending_users = User.query.filter_by(is_approved=False).order_by(User.registered_on.desc()).all()

    # 승인된 사용자 목록
    approved_users = User.query.filter_by(is_approved=True).order_by(User.username).all()

    return render_template('admin/panel.html',
                           title='관리자 패널',
                           pending_users=pending_users,
                           approved_users=approved_users)


@bp.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(user_id)
    user.is_approved = True
    user.approved_on = kst_now()
    user.approved_by = current_user.id
    db.session.commit()

    flash(f'사용자 {user.username}의 계정이 승인되었습니다.', 'success')

    # 사용자에게 승인 알림 (선택 사항)
    notify_user_approval(user)

    return redirect(url_for('main.admin_panel'))


@bp.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_user(user_id):
    # 관리자 권한 확인
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(user_id)

    # 사용자에게 거부 알림 (선택 사항)
    notify_user_rejection(user)

    # 사용자 삭제
    db.session.delete(user)
    db.session.commit()

    flash(f'사용자 {user.username}의 가입 요청이 거부되었습니다.', 'info')
    return redirect(url_for('main.admin_panel'))


def notify_user_approval(user):
    """사용자에게 계정 승인 알림"""
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    logger.info(f"사용자 {user.username}에게 계정 승인 알림")


def notify_user_rejection(user):
    """사용자에게 계정 거부 알림"""
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    logger.info(f"사용자 {user.username}에게 계정 거부 알림")


# 티커별 거래 기록 가져오는 API 엔드포인트 수정
@bp.route('/api/trade_records')
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


@bp.route('/api/trade_records/<ticker>')
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


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = TradingSettingsForm()
    favorite_form = FavoriteForm()
    favorite_id = request.args.get('favorite_id', type=int)

    # 즐겨찾기 불러오기 (GET 요청 시)
    if request.method == 'GET' and favorite_id:
        favorite = TradingFavorite.query.get_or_404(favorite_id)
        if favorite.user_id != current_user.id:
            flash('해당 즐겨찾기에 대한 권한이 없습니다.', 'danger')
            return redirect(url_for('main.favorites'))

        # 폼에 데이터 채우기
        form.process(data=favorite.to_dict())
        flash(f'"{favorite.name}" 설정을 불러왔습니다. 필요시 수정 후 봇을 실행하세요.', 'info')

    # (기존) 설정 저장 및 봇 실행 로직 (POST 요청 시)
    if form.validate_on_submit() and request.method == 'POST' and not favorite_id:
        # 여기에 기존의 설정 저장 또는 봇 실행 로직이 위치합니다.
        ticker = form.ticker.data
        strategy_name = form.strategy.data
        # print(ticker, strategy_name)
        start_bot(ticker, strategy_name, form)
        flash('거래 설정이 적용되었습니다.', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('settings.html', title='거래 설정', form=form, favorite_form=favorite_form)


@bp.route('/favorites')
@login_required
def favorites():
    favorites = TradingFavorite.query.filter_by(user_id=current_user.id).order_by(TradingFavorite.created_at.desc()).all()
    return render_template('favorites.html', title='즐겨찾기', favorites=favorites)


@bp.route('/save_favorite', methods=['POST'])
@login_required
def save_favorite():
    settings_form = TradingSettingsForm(request.form)
    favorite_form = FavoriteForm(request.form)

    if favorite_form.name.data:
        favorite = TradingFavorite(
            user_id=current_user.id,
            name=favorite_form.name.data
        )
        # settings_form의 데이터로 favorite 객체 채우기
        for field in settings_form:
            if hasattr(favorite, field.name):
                setattr(favorite, field.name, field.data)

        db.session.add(favorite)
        db.session.commit()
        flash(f'"{favorite.name}" 이름으로 즐겨찾기에 저장되었습니다.', 'success')
        return redirect(url_for('main.favorites'))
    else:
        flash('즐겨찾기 저장에 실패했습니다. 유효한 이름을 입력해주세요.', 'danger')
        # 원래 폼 데이터를 유지하며 settings 페이지로 돌아가기
        return render_template('settings.html', title='거래 설정', form=settings_form, favorite_form=favorite_form)


@bp.route('/delete_favorite/<int:favorite_id>')
@login_required
def delete_favorite(favorite_id):
    favorite = TradingFavorite.query.get_or_404(favorite_id)
    if favorite.user_id != current_user.id:
        flash('해당 즐겨찾기에 대한 권한이 없습니다.', 'danger')
        return redirect(url_for('main.favorites'))

    db.session.delete(favorite)
    db.session.commit()
    flash('즐겨찾기가 삭제되었습니다.', 'success')
    return redirect(url_for('main.favorites'))


def stop_all_bots():
    """모든 트레이딩 봇 종료 처리"""
    with lock:
        for user_id, ticker_data in trading_bots.items():
            for ticker, bot_info in ticker_data.items():
                bot_info['running'] = False  # 봇 상태 플래그 False로 설정
                logger.info(f"봇 중지 플래그 설정: {ticker} (User ID: {user_id})")

        # 스레드 종료 완료 대기
        time.sleep(2)
        logger.info("모든 봇이 안전하게 중지되었습니다.")


# 스레드 모니터링 라우트들
@bp.route('/thread-monitor')
@login_required
def thread_monitor_dashboard():
    """스레드 모니터링 대시보드"""
    return render_template('thread_monitor.html')


@bp.route('/api/thread-monitor/stats')
@login_required
def get_thread_stats():
    """현재 스레드 통계 API"""
    from dataclasses import asdict
    stats = thread_monitor.collect_stats()
    return jsonify(asdict(stats))


@bp.route('/api/thread-monitor/details')
@login_required
def get_thread_details():
    """상세 스레드 정보 API"""
    return jsonify({'threads': thread_monitor.get_thread_details()})


@bp.route('/api/thread-monitor/performance')
@login_required
def get_performance_report():
    """성능 리포트 API"""
    hours = request.args.get('hours', 24, type=int)
    return jsonify(thread_monitor.get_performance_report(hours))


@bp.route('/api/thread-monitor/alerts')
@login_required
def get_alerts():
    """알림 목록 API"""
    return jsonify({'alerts': thread_monitor.alerts})


@bp.route('/api/thread-monitor/gc', methods=['POST'])
@login_required
def force_gc():
    """강제 가비지 컬렉션 API"""
    result = thread_monitor.force_garbage_collection()
    return jsonify({'success': True, 'result': result})


@bp.route('/api/thread-monitor/export')
@login_required
def export_thread_stats():
    """통계 내보내기 API"""
    import os
    from datetime import datetime

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'thread_stats_{timestamp}.json'
    # 프로젝트 루트 디렉토리 얻기
    basedir = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.dirname(basedir)  # app 디렉토리에서 상위로 이동
    filepath = os.path.join(project_root, 'logs', filename)

    thread_monitor.export_stats(filepath)

    return send_file(filepath, as_attachment=True, download_name=filename)


# ===========================================
# 스레드 제어 API 라우트들
# ===========================================

@bp.route('/api/threads/status')
@login_required
def api_get_thread_status():
    """스레드 상태 조회 API"""
    try:
        user_id = request.args.get('user_id', type=int)
        ticker = request.args.get('ticker')

        # 관리자가 아닌 경우 자신의 스레드만 조회 가능
        if not current_user.is_admin and user_id and user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '권한이 없습니다'
            }), 403

        # 일반 사용자는 자신의 스레드만 조회
        if not current_user.is_admin:
            user_id = current_user.id

        status = get_thread_status(user_id, ticker)

        return jsonify({
            'success': True,
            'data': status
        })

    except Exception as e:
        logger.error(f"스레드 상태 조회 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'스레드 상태 조회 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/stop', methods=['POST'])
@login_required
def api_stop_thread():
    """특정 스레드 중지 API"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        ticker = data.get('ticker')
        force = data.get('force', False)

        if not user_id or not ticker:
            return jsonify({
                'success': False,
                'message': 'user_id와 ticker는 필수입니다'
            }), 400

        # 권한 확인: 관리자가 아닌 경우 자신의 스레드만 중지 가능
        if not current_user.is_admin and user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '권한이 없습니다'
            }), 403

        result = stop_thread(user_id, ticker, force)

        if result.success:
            flash(f'스레드 중지됨: {ticker}', 'success')
            logger.info(f"스레드 중지: User {current_user.id}가 User {user_id}의 {ticker} 스레드 중지")
        else:
            flash(f'스레드 중지 실패: {result.message}', 'error')

        return jsonify({
            'success': result.success,
            'message': result.message,
            'data': {
                'user_id': result.user_id,
                'ticker': result.ticker,
                'thread_id': result.thread_id,
                'stop_time': result.stop_time.isoformat() if result.stop_time else None
            }
        })

    except Exception as e:
        logger.error(f"스레드 중지 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'스레드 중지 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/stop-user', methods=['POST'])
@login_required
def api_stop_user_threads():
    """사용자의 모든 스레드 중지 API"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        force = data.get('force', False)

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'user_id는 필수입니다'
            }), 400

        # 권한 확인
        if not current_user.is_admin and user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '권한이 없습니다'
            }), 403

        results = stop_user_threads(user_id, force)
        successful_stops = [r for r in results if r.success]
        failed_stops = [r for r in results if not r.success]

        if successful_stops:
            flash(f'{len(successful_stops)}개 스레드가 중지되었습니다', 'success')
            logger.info(f"사용자 스레드 중지: User {current_user.id}가 User {user_id}의 {len(successful_stops)}개 스레드 중지")

        if failed_stops:
            flash(f'{len(failed_stops)}개 스레드 중지 실패', 'error')

        return jsonify({
            'success': len(failed_stops) == 0,
            'message': f'{len(successful_stops)}개 성공, {len(failed_stops)}개 실패',
            'data': {
                'successful_stops': len(successful_stops),
                'failed_stops': len(failed_stops),
                'results': [
                    {
                        'success': r.success,
                        'user_id': r.user_id,
                        'ticker': r.ticker,
                        'message': r.message,
                        'stop_time': r.stop_time.isoformat() if r.stop_time else None
                    } for r in results
                ]
            }
        })

    except Exception as e:
        logger.error(f"사용자 스레드 중지 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'사용자 스레드 중지 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/stop-all', methods=['POST'])
@login_required
def api_stop_all_threads():
    """모든 스레드 중지 API (관리자만)"""
    try:
        # 관리자 권한 확인
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '관리자 권한이 필요합니다'
            }), 403

        data = request.get_json() or {}
        force = data.get('force', False)

        results = stop_all_threads(force)
        successful_stops = [r for r in results if r.success]
        failed_stops = [r for r in results if not r.success]

        if successful_stops:
            flash(f'모든 스레드 중지 완료: {len(successful_stops)}개', 'success')
            logger.warning(f"전체 스레드 중지: 관리자 {current_user.username}이 {len(successful_stops)}개 스레드 중지")

        if failed_stops:
            flash(f'{len(failed_stops)}개 스레드 중지 실패', 'error')

        return jsonify({
            'success': len(failed_stops) == 0,
            'message': f'전체 중지 완료: {len(successful_stops)}개 성공, {len(failed_stops)}개 실패',
            'data': {
                'successful_stops': len(successful_stops),
                'failed_stops': len(failed_stops),
                'total_processed': len(results)
            }
        })

    except Exception as e:
        logger.error(f"전체 스레드 중지 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'전체 스레드 중지 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/emergency-stop', methods=['POST'])
@login_required
def api_emergency_stop():
    """긴급 중지 API (관리자만)"""
    try:
        # 관리자 권한 확인
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '관리자 권한이 필요합니다'
            }), 403

        results = emergency_stop()

        flash('긴급 중지가 실행되었습니다', 'warning')
        logger.critical(f"긴급 중지 실행: 관리자 {current_user.username}")

        return jsonify({
            'success': True,
            'message': '긴급 중지 완료',
            'data': {
                'total_processed': len(results)
            }
        })

    except Exception as e:
        logger.error(f"긴급 중지 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'긴급 중지 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/restart', methods=['POST'])
@login_required
def api_restart_thread():
    """스레드 재시작 API"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        ticker = data.get('ticker')

        if not user_id or not ticker:
            return jsonify({
                'success': False,
                'message': 'user_id와 ticker는 필수입니다'
            }), 400

        # 권한 확인
        if not current_user.is_admin and user_id != current_user.id:
            return jsonify({
                'success': False,
                'message': '권한이 없습니다'
            }), 403

        result = thread_controller.restart_thread(user_id, ticker)

        if result.success:
            flash(f'스레드 재시작: {ticker}', 'success')
        else:
            flash(f'스레드 재시작 실패: {result.message}', 'error')

        return jsonify({
            'success': result.success,
            'message': result.message,
            'data': {
                'user_id': result.user_id,
                'ticker': result.ticker
            }
        })

    except Exception as e:
        logger.error(f"스레드 재시작 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'스레드 재시작 실패: {str(e)}'
        }), 500


@bp.route('/api/threads/history')
@login_required
def api_get_stop_history():
    """스레드 중지 이력 조회 API (관리자만)"""
    try:
        # 관리자 권한 확인
        if not current_user.is_admin:
            return jsonify({
                'success': False,
                'message': '관리자 권한이 필요합니다'
            }), 403

        limit = request.args.get('limit', 50, type=int)
        history = thread_controller.get_stop_history(limit)

        return jsonify({
            'success': True,
            'data': {
                'history': history,
                'total_count': len(history)
            }
        })

    except Exception as e:
        logger.error(f"중지 이력 조회 API 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'중지 이력 조회 실패: {str(e)}'
        }), 500


# ===========================================
# 웹 페이지 라우트들
# ===========================================

@bp.route('/thread-control')
@login_required
def thread_control_page():
    """스레드 제어 페이지"""
    # 관리자만 전체 제어 페이지 접근 가능
    if current_user.is_admin:
        return render_template('thread_control.html', is_admin=True)
    else:
        # 일반 사용자는 자신의 스레드만 제어 가능
        return render_template('thread_control.html', is_admin=False, user_id=current_user.id)


# ===========================================
# 기존 거래 페이지에 중지 버튼 추가를 위한 라우트 수정
# ===========================================

@bp.route('/trading')
@login_required
def trading_dashboard():
    """거래 대시보드 (스레드 상태 포함)"""
    try:
        # 사용자의 스레드 상태 조회
        user_status = get_thread_status(current_user.id)

        return render_template('trading.html',
                               thread_status=user_status,
                               user_id=current_user.id,
                               is_admin=current_user.is_admin)
    except Exception as e:
        logger.error(f"거래 대시보드 로드 오류: {str(e)}")
        flash('대시보드 로드 중 오류가 발생했습니다', 'error')
        return render_template('trading.html',
                               thread_status={'threads': []},
                               user_id=current_user.id,
                               is_admin=current_user.is_admin)