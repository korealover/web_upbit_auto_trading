from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from flask_socketio import emit
from app import db, socketio
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm, ProfileForm
from app.models import User, TradeRecord, kst_now
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
from app.utils.caching import cache_with_timeout


# Blueprint 생성
bp = Blueprint('main', __name__)

# 전역 변수
trading_bots = {}
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


@bp.route('/settings', methods=['GET', 'POST'])
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
        return redirect(url_for('main.dashboard'))

    return render_template('settings.html', form=form)


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

    # 봇 생성 - WebSocket 지원을 위한 로거 생성
    websocket_logger = WebSocketLogger(ticker, user_id)
    bot = UpbitTradingBot(settings, upbit_api, strategy, websocket_logger)

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

from app.utils.caching import cache_with_timeout


@bp.route('/api/logs/<ticker>')
@login_required
@cache_with_timeout(seconds=30, max_size=50)  # 30초 캐싱
def get_ticker_logs(ticker):
    """특정 티커의 로그 조회 (캐싱 적용)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    days_back = request.args.get('days', 2, type=int)  # 기본 2일만 조회

    # 최대 제한
    per_page = min(per_page, 100)
    days_back = min(days_back, 7)

    return _get_logs_cached(ticker, page, per_page, days_back)


@bp.route('/api/logs')
@login_required
@cache_with_timeout(seconds=30, max_size=50)  # 30초 캐싱
def get_all_logs():
    """전체 로그 조회 (캐싱 적용)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    days_back = request.args.get('days', 2, type=int)  # 기본 2일만 조회

    # 최대 제한
    per_page = min(per_page, 100)
    days_back = min(days_back, 7)

    return _get_logs_cached('', page, per_page, days_back)


def _get_logs_cached(ticker, page=1, per_page=50, days_back=2):
    """캐싱된 로그 조회 (내부 함수)"""
    log_dir = 'logs'
    all_logs = []

    try:
        # 지정된 일수만큼 로그 파일 확인
        for days_back_idx in range(days_back):
            check_date = (datetime.now() - timedelta(days=days_back_idx)).strftime('%Y%m%d')

            if ticker:
                ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
                log_filename = f"{check_date}_{ticker_symbol}.log"
            else:
                log_filename = f"{check_date}_web.log"

            log_path = os.path.join(log_dir, log_filename)

            if os.path.exists(log_path):
                # 각 파일에서 제한된 수만 읽기 (성능 최적화)
                lines_limit = 200 if days_back_idx == 0 else 100  # 오늘은 더 많이, 이전은 적게
                file_logs = tail_file_optimized(log_path, lines_limit)

                for line in file_logs:
                    parts = line.strip().split(' - ', 2)
                    if len(parts) >= 3:
                        timestamp, level, message = parts
                        message = html.escape(message)
                        all_logs.append({
                            'timestamp': timestamp,
                            'level': level,
                            'message': message,
                            'date': check_date
                        })

        # 시간순 정렬 (최신 순)
        all_logs.sort(key=lambda x: x['timestamp'], reverse=True)

        # 페이지네이션 적용
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        logs_page = all_logs[start_idx:end_idx]

        return jsonify({
            'logs': logs_page,
            'total': len(all_logs),
            'page': page,
            'per_page': per_page,
            'has_next': end_idx < len(all_logs),
            'has_prev': page > 1
        })

    except Exception as e:
        logger.error(f"로그 조회 오류: {str(e)}")
        return jsonify({'error': '로그를 불러오는 중 오류가 발생했습니다.'}), 500


def tail_file_optimized(file_path, n=100):
    """최적화된 파일 tail 읽기"""
    try:
        # 파일 크기 먼저 확인
        file_size = os.path.getsize(file_path)

        # 빈 파일이거나 매우 작은 파일
        if file_size == 0:
            return []

        # 작은 파일 (50KB 미만)은 전체 읽기
        if file_size < 51200:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return [line.rstrip() for line in lines if line.strip()][-n:]

        # 큰 파일은 끝부분만 읽기
        with open(file_path, 'r', encoding='utf-8') as f:
            # 파일 끝에서 적당한 크기만큼 읽기 (보통 마지막 몇 KB면 충분)
            read_size = min(file_size, n * 200)  # 라인당 평균 200바이트 가정
            f.seek(max(0, file_size - read_size))

            # 첫 번째 불완전한 라인 건너뛰기
            if f.tell() > 0:
                f.readline()

            lines = f.readlines()
            return [line.rstrip() for line in lines if line.strip()][-n:]

    except Exception as e:
        logger.error(f"파일 읽기 오류 ({file_path}): {str(e)}")
        return []


def tail_file(file_path, n=100):
    """파일의 마지막 n줄 읽기 (개선된 버전)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 파일 끝으로 이동
            f.seek(0, 2)
            file_size = f.tell()

            # 빈 파일 체크
            if file_size == 0:
                return []

            # 작은 파일의 경우 전체 읽기
            if file_size < 8192:  # 8KB 미만
                f.seek(0)
                lines = f.readlines()
                return [line for line in lines if line.strip()][-n:]

            # 큰 파일의 경우 역방향 읽기
            lines = []
            chars_read = 0
            buffer_size = 8192  # 8KB씩 읽기

            while len(lines) < n and chars_read < file_size:
                # 읽을 크기 결정
                chunk_size = min(buffer_size, file_size - chars_read)

                # 파일 포인터 이동
                f.seek(file_size - chars_read - chunk_size)
                chunk = f.read(chunk_size)
                chars_read += chunk_size

                # 줄 단위로 분리
                chunk_lines = chunk.split('\n')

                # 이전에 읽은 데이터와 병합
                if lines and chunk_lines[-1]:
                    lines[0] = chunk_lines[-1] + lines[0]
                    chunk_lines = chunk_lines[:-1]

                # 새로운 줄들을 앞에 추가
                lines = [line for line in chunk_lines if line.strip()] + lines

            return lines[-n:] if len(lines) > n else lines

    except Exception as e:
        logger.error(f"파일 읽기 오류 ({file_path}): {str(e)}")
        return []


@bp.route('/api/active-tickers')
@login_required
def get_active_tickers():
    """활성 티커 목록 반환"""
    try:
        # 현재 실행 중인 봇들의 티커 목록
        active_tickers = []

        # trading_bots 딕셔너리에서 실행 중인 봇들 확인
        for ticker, bot_info in trading_bots.items():
            if bot_info and bot_info.get('status') == 'running':
                active_tickers.append({
                    'ticker': ticker,
                    'status': 'running',
                    'start_time': bot_info.get('start_time', ''),
                    'last_update': bot_info.get('last_update', '')
                })

        return jsonify({
            'active_tickers': active_tickers,
            'total_count': len(active_tickers)
        })

    except Exception as e:
        logger.error(f"활성 티커 조회 오류: {str(e)}")
        return jsonify({'error': '활성 티커를 불러오는 중 오류가 발생했습니다.'}), 500


@bp.route('/api/all-tickers')
@login_required
def get_all_tickers():
    """전체 사용 가능한 티커 목록 반환"""
    try:
        from app.utils.tickers import get_ticker_choices

        # 사용 가능한 모든 티커 목록
        all_tickers = get_ticker_choices()

        # 형태를 API 응답에 맞게 변환
        ticker_list = []
        for ticker_code, display_name in all_tickers:
            ticker_list.append({
                'ticker': ticker_code,
                'name': display_name,
                'symbol': ticker_code.split('-')[1] if '-' in ticker_code else ticker_code
            })

        return jsonify({
            'tickers': ticker_list,
            'total_count': len(ticker_list)
        })

    except Exception as e:
        logger.error(f"티커 목록 조회 오류: {str(e)}")
        return jsonify({'error': '티커 목록을 불러오는 중 오류가 발생했습니다.'}), 500

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