from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from app import db, socketio
from app.forms import TradingSettingsForm, LoginForm, RegistrationForm, ProfileForm, FavoriteForm
from app.models import User, TradeRecord, kst_now, TradingFavorite
from app.api.upbit_api import UpbitAPI
from app.strategy import create_strategy
from app.utils.logging_utils import setup_logger, get_logger_with_current_date
from app.utils.async_utils import AsyncHandler
from app.utils.shared import scheduled_bots
from app.bot.trading_bot import UpbitTradingBot
import time
import os
from datetime import datetime
from app.utils.scheduler_manager import scheduler_manager
import uuid

# Blueprint 생성
bp = Blueprint('main', __name__)

# 전역 변수
async_handler = AsyncHandler(max_workers=5)
upbit_apis = {}  # 사용자별 API 객체 저장
logger = setup_logger('web', 'INFO', 7)

# 메인 페이지
@bp.route('/')
def index():
    return render_template('index.html')


# 로그인
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
        flash('로그인 되었습니다!', 'success')
        return redirect(next_page)
    return render_template('login.html', title='로그인', form=form)


# 로그아웃
@bp.route('/logout')
def logout():
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('main.index'))


# 회원가입
@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            is_approved=False  # 기본적으로 승인되지 않은 상태
        )

        user.set_password(form.password.data)
        user.set_upbit_keys(form.upbit_access_key.data, form.upbit_secret_key.data)
        db.session.add(user)
        db.session.commit()

        # 승인 필요 메시지
        flash('회원가입이 완료되었습니다! 관리자 승인 후 로그인할 수 있습니다.', 'info')

        # 관리자에게 새 가입자 알림 (선택 사항)
        notify_admin_new_registration(user)

        return redirect(url_for('main.login'))
    return render_template('register.html', title='회원가입', form=form)


# 관리자 회원 가입 알림
def notify_admin_new_registration(user):
    """관리자에게 새 회원가입 알림"""
    admins = User.query.filter_by(is_admin=True).all()
    # 이메일 전송 또는 알림 로직 구현 (별도 구현 필요)
    for admin in admins:
        logger.info(f"관리자 {admin.username}에게 새 회원 {user.username} 가입 알림")


# 회원 프로필
@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(current_user.username, current_user.email)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.email = form.email.data

        # API 객체 재생성 (API 키가 변경된 경우)
        if form.upbit_access_key.data or form.upbit_secret_key.data:
            user_id = current_user.id
            if user_id in upbit_apis:
                del upbit_apis[user_id]  # 기존 API 객체 제거

            # 만약 사용자의 봇이 실행 중이었다면 중지
            if user_id in scheduled_bots:
                for ticker in list(scheduled_bots[user_id].keys()):
                    scheduled_bots[user_id][ticker]['running'] = False
                scheduled_bots[user_id] = {}

            # API 키 암호화 저장
            access_key = form.upbit_access_key.data
            secret_key = form.upbit_secret_key.data

            try:
                current_user.set_upbit_keys(access_key, secret_key)
                db.session.commit()
                flash('프로필이 성공적으로 업데이트되었습니다.', 'success')
            except ValueError as e:
                flash(f'API 키 저장 실패: {str(e)}', 'error')
                return redirect(url_for('main.profile'))

        flash('프로필이 업데이트되었습니다.', 'success')
        return redirect(url_for('main.profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.email.data = current_user.email
        # API 키는 보안상 폼에 미리 채우지 않음

    return render_template('profile.html', title='프로필', form=form)


# 업비트 Key 유효성 검증
@bp.route('/validate_api_keys', methods=['POST'])
@login_required
def validate_api_keys():
    try:
        upbit_api = UpbitAPI.create_from_user(current_user, async_handler, logger)
        is_valid, error_msg = upbit_api.validate_api_keys()

        if is_valid:
            return jsonify({'success': True, 'message': 'API 키가 유효합니다.'})
        else:
            return jsonify({'success': False, 'error': error_msg})

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)})


@bp.route('/dashboard')
@login_required
def dashboard():
    """대시보드 페이지"""
    user_id = current_user.id
    try:
        # 사용자 정보 확인
        user = User.query.get(current_user.id)
        if not user:
            flash('사용자 정보를 찾을 수 없습니다.')
            return redirect(url_for('main.login'))

        # API 키 존재 여부 확인
        try:
            access_key, secret_key = user.get_upbit_keys()
            if not access_key or not secret_key:
                flash('업비트 API 키가 설정되지 않았습니다. 프로필 페이지에서 API 키를 등록해주세요.', 'warning')
                return render_template('dashboard.html',
                                       user=user,
                                       api_keys_missing=True,
                                       active_bots=[],
                                       balance_info=None)
        except Exception as e:
            logger.error(f"API 키 복호화 실패: {str(e)}")
            flash('API 키 복호화에 실패했습니다. 프로필 페이지에서 API 키를 다시 설정해주세요.', 'error')
            return render_template('dashboard.html',
                                   user=user,
                                   api_keys_missing=True,
                                   active_bots=[],
                                   balance_info=None)

        # 기존 대시보드 로직 계속...
        # API 키가 정상적으로 설정된 경우에만 UpbitAPI 객체 생성
        try:
            if user_id not in upbit_apis:
                # UpbitAPI 클래스에서 자동으로 복호화 처리
                api = UpbitAPI.create_from_user(current_user, async_handler, logger)

                # API 키 유효성 검증
                is_valid, error_msg = api.validate_api_keys()
                if not is_valid:
                    logger.error("업비트 키 복호화 에러")
                    return None

                # 잔고 정보 조회
            balance_info = {}
            try:
                # 사용자별 봇 정보 가져오기
                user_bots = scheduled_bots.get(user_id, {})

                # 봇 정보 정규화 및 템플릿 호환성 개선
                for ticker, bot_info in user_bots.items():
                    # print(f'user_id: {user_id}, ticker: {ticker}, bot_info: {bot_info}')
                    try:
                        # 마지막 로그에서 신호 시간 추출
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

                        # 템플릿 호환성을 위한 설정 구조 개선
                        if 'interval_label' in bot_info:
                            bot_info['interval_label'] = get_selected_label(bot_info['interval_label'])

                        # 장기투자 여부
                        if 'long_term_investment' in bot_info:
                            bot_info['long_term_investment'] = bot_info['long_term_investment']

                        # 실행 상태 확인
                        if 'running' in bot_info:
                            bot_info['running'] = True if bot_info['running'] else False
                        else:
                            bot_info['running'] = False

                        # settings 정규화 - Form 객체와 딕셔너리 모두 처리
                        settings = bot_info.get('settings', {})
                        normalized_settings = {}

                        def get_setting_value(setting_obj, default_value=None):
                            """설정 값을 안전하게 추출"""
                            if setting_obj is None:
                                return default_value
                            if hasattr(setting_obj, 'data'):
                                return setting_obj.data
                            return setting_obj

                        def safe_numeric_value(value, default=0):
                            """숫자 값을 안전하게 변환"""
                            if value is None:
                                return default
                            if isinstance(value, (int, float)):
                                return value
                            if isinstance(value, str):
                                try:
                                    return float(value) if '.' in value else int(value)
                                except (ValueError, TypeError):
                                    return default
                            return default

                        # 필요한 설정 필드들을 정규화
                        setting_fields = {
                            'buy_amount': 0,
                            'min_cash': 0,
                            'sell_portion': 100,
                            'prevent_loss_sale': 'Y',
                            'long_term_investment': 'N',
                            'sleep_time': 60,
                            'ticker': ticker,
                            'strategy': bot_info.get('strategy', ''),
                            'interval': bot_info.get('interval', ''),
                            'name': bot_info.get('name', ''),
                            'window': 20,
                            'multiplier': 2.0,
                            'buy_multiplier': 3.0,
                            'sell_multiplier': 2.0,
                            'k': 0.5,
                            'target_profit': 1.0,
                            'stop_loss': 3.0,
                            'rsi_period': 14,
                            'rsi_oversold': 30,
                            'rsi_overbought': 70,
                            'rsi_timeframe': 'minute5'
                        }

                        for field_name, default_value in setting_fields.items():
                            if isinstance(settings, dict):
                                # 딕셔너리 형태의 settings (DB에서 복원된 경우)
                                raw_value = settings.get(field_name, default_value)

                                # 숫자 필드들은 안전하게 변환
                                if field_name in ['buy_amount', 'min_cash', 'sell_portion', 'sleep_time', 'window', 'multiplier', 'buy_multiplier', 'sell_multiplier', 'k', 'target_profit', 'stop_loss', 'rsi_period',
                                                  'rsi_oversold', 'rsi_overbought']:
                                    raw_value = safe_numeric_value(raw_value, default_value)

                                # 템플릿에서 직접 접근 가능하도록 간단한 구조로 변경
                                normalized_settings[field_name] = raw_value
                            else:
                                # Form 객체 형태의 settings (웹에서 설정된 경우)
                                if hasattr(settings, field_name):
                                    field_obj = getattr(settings, field_name)
                                    raw_value = get_setting_value(field_obj, default_value)

                                    # 숫자 필드들은 안전하게 변환
                                    if field_name in ['buy_amount', 'min_cash', 'sell_portion', 'sleep_time', 'window', 'multiplier', 'buy_multiplier', 'sell_multiplier', 'k', 'target_profit', 'stop_loss',
                                                      'rsi_period',
                                                      'rsi_oversold', 'rsi_overbought']:
                                        raw_value = safe_numeric_value(raw_value, default_value)

                                    normalized_settings[field_name] = raw_value
                                else:
                                    normalized_settings[field_name] = default_value

                        # bot_info에 정규화된 settings 적용
                        bot_info['settings'] = normalized_settings

                        # 전략별 특수 필드 처리
                        strategy = bot_info.get('strategy', '')
                        if strategy == 'bollinger':
                            # 볼린저 밴드 전략 관련 필드 확인
                            if 'window' not in normalized_settings:
                                normalized_settings['window'] = 20
                            if 'multiplier' not in normalized_settings:
                                normalized_settings['multiplier'] = 2.0
                            if 'buy_multiplier' not in normalized_settings:
                                normalized_settings['buy_multiplier'] = 3.0
                            if 'sell_multiplier' not in normalized_settings:
                                normalized_settings['sell_multiplier'] = 2.0

                    except Exception as e:
                        logger.warning(f"봇 {ticker} 정보 처리 실패: {str(e)}")
                        bot_info['last_signal_time'] = None
                        bot_info['running'] = False
                        # 기본 설정 구조 생성
                        bot_info['settings'] = {
                            'buy_amount': 0,
                            'min_cash': 0,
                            'sell_portion': 100,
                            'prevent_loss_sale': 'Y',
                            'long_term_investment': 'N',
                            'sleep_time': 60,
                            'ticker': ticker,
                            'strategy': '',
                            'interval': '',
                            'name': '',
                            'window': 20,
                            'multiplier': 2.0,
                            'buy_multiplier': 2.0,
                            'sell_multiplier': 2.0
                        }

                # 업비트 잔고 확인
                balance_info['cash'] = api.get_balance_cash()
                if balance_info['cash'] is None:
                    balance_info['cash'] = 0

                # 보유 코인 정보 조회 - pyupbit를 직접 사용
                try:
                    all_balances = api.upbit.get_balances()
                    balance_info['coins'] = []
                    total_balance = balance_info['cash']

                    if all_balances:
                        for balance in all_balances:
                            if balance['currency'] != 'KRW' and float(balance['balance']) > 0:
                                ticker = f"KRW-{balance['currency']}"
                                try:
                                    # 현재 코인 가격
                                    current_price = api.get_current_price(ticker)
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

            # 거래 기록 조회 (최근 20개)
            trade_records = TradeRecord.query.filter_by(
                user_id=current_user.id
            ).order_by(
                TradeRecord.timestamp.desc()
            ).limit(20).all()

            return render_template('dashboard.html',
                                   balance_info=balance_info,
                                   scheduled_bots=user_bots,
                                   trade_records=trade_records,
                                   daily_stats=daily_stats,
                                   strategy_performance=strategy_performance)

        except Exception as e:
            logger.error(f"대시보드 로딩 중 오류: {str(e)}")
            flash('대시보드 로딩 중 오류가 발생했습니다.', 'error')
            return render_template('dashboard.html',
                                   user=user,
                                   api_keys_missing=True,
                                   active_bots=[],
                                   balance_info=None)

    except Exception as e:
        logger.error(f"대시보드 접근 중 오류: {str(e)}")
        flash('시스템 오류가 발생했습니다.', 'error')
        return redirect(url_for('main.index'))


# 자동매매 설정
@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """APScheduler를 사용한 자동매매 셋팅"""
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
        try:
            # 여기에 기존의 설정 저장 또는 봇 실행 로직이 위치합니다.
            ticker = form.ticker.data
            strategy_name = form.strategy.data
            # 매수/매도 거래 시작
            start_bot(ticker, strategy_name, form)
            # 거래 설정 완료 후 자동으로 즐겨찾기에 저장
            # 즐겨찾기 저장 요청이 있는 경우
            save_to_favorites = request.form.get('save_to_favorites')
            if save_to_favorites == 'true':
                auto_save_result = auto_save_favorite_from_settings(request.form)
                if auto_save_result['success']:
                    flash(f'거래 설정이 완료되고 "{auto_save_result["name"]}"으로 즐겨찾기에 저장되었습니다.', 'success')
                else:
                    flash('거래 설정은 완료되었지만 즐겨찾기 저장에 실패했습니다.', 'warning')
            else:
                flash('거래 설정이 적용되었습니다.', 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            logger.error(f"Settings 처리 중 오류: {e}")
            flash('설정 저장 중 오류가 발생했습니다.', 'danger')

    return render_template('settings.html', title='거래 설정', form=form, favorite_form=favorite_form)


# 자동매매 시작
def start_bot(ticker, strategy_name, settings):
    """APScheduler를 사용한 자동매매 시작"""
    user_id = current_user.id
    try:
        logger = get_logger_with_current_date(ticker, 'INFO', 7)
        # 기존에 같은 ticker 관련 봇이 있다면 삭제 진행
        if user_id in scheduled_bots:
            if ticker in scheduled_bots[user_id]:
                old_job_id = scheduled_bots[user_id][ticker]['job_id']
                scheduler_manager.remove_job(old_job_id)
                logger.info(f"기존 스케줄 작업 중지: {user_id} / {ticker} / {old_job_id}")
                time.sleep(2)
            # return
    except Exception as e:
        logger.error(f"기존 스케줄 작업 중지 에러: {e}")

    with scheduler_manager.lock:
        # 초기화
        if user_id not in scheduled_bots:
            scheduled_bots[user_id] = {}

        # API 초기화
        if user_id not in upbit_apis:
            # UpbitAPI 클래스에서 자동으로 복호화 처리
            upbit_api = UpbitAPI.create_from_user(current_user, async_handler, logger)

            # API 키 유효성 검증
            is_valid, error_msg = upbit_api.validate_api_keys()
            if not is_valid:
                logger.error("업비트 키 복호화 에러")
                return None

    strategy = create_strategy(strategy_name, upbit_api, logger)

    # settings에 user_id 추가
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

    # 거래 간격 설정
    if hasattr(settings, 'sleep_time'):
        sleep_time = settings.sleep_time.data if hasattr(settings.sleep_time, 'data') else settings.sleep_time
    elif isinstance(settings, dict) and 'sleep_time' in settings:
        sleep_time = settings['sleep_time']
    else:
        sleep_time = 60  # 기본값

    # 장기 투자 여부
    if hasattr(settings, 'long_term_investment'):
        long_term_investment = settings.long_term_investment.data if hasattr(settings.long_term_investment, 'data') else settings.long_term_investment
    elif isinstance(settings, dict) and 'long_term_investment' in settings:
        long_term_investment = settings['long_term_investment']
    else:
        long_term_investment = 'N'  # 기본값

    # 고유한 작업 ID 생성
    job_id = f"Trading_bot_{user_id}_{ticker}_{strategy_name}_{uuid.uuid4().hex[:8]}"

    # 스케줄러에 작업 추가 - 수정된 부분
    success = scheduler_manager.add_trading_job(
        job_id=job_id,
        trading_func=lambda: scheduled_trading_cycle(user_id, ticker, bot, websocket_logger),
        interval_seconds=sleep_time,
        user_id=user_id,
        ticker=ticker,
        strategy=strategy_name
    )

    if success:
        with scheduler_manager.lock:
            scheduled_bots[user_id][ticker] = {
                'job_id': job_id,
                'bot': bot,
                'strategy': strategy_name,
                'settings': settings,
                'interval': sleep_time,
                'start_time': datetime.now(),
                'username': current_user.username,
                'cycle_count': 0,
                'last_run': None,
                'running': True,  # 실행 상태 추가
                'interval_label': get_selected_label(settings['interval']),  # 수정된 부분: sleep_time 직접 전달
                'long_term_investment': long_term_investment
            }

        logger.info(f"APScheduler 봇 시작 성공: {ticker} (Job ID: {job_id})")
        return job_id
    else:
        logger.error(f"APScheduler 봇 시작 실패: {ticker}")
        return None


# 스케줄러 호출
def scheduled_trading_cycle(user_id, ticker, bot=None, websocket_logger=None):
    """스케줄된 트레이딩 사이클 실행 - 에러 처리 강화"""
    cycle_count = 1
    if user_id in scheduled_bots and ticker in scheduled_bots[user_id]:
        scheduled_bots[user_id][ticker]['cycle_count'] += 1
        cycle_count = scheduled_bots[user_id][ticker]['cycle_count']
        scheduled_bots[user_id][ticker]['last_run'] = datetime.now()

    logger.info(f"트레이딩 사이클 시작: {user_id}/{ticker} (#{cycle_count})")

    try:
        # 봇 정보 확인 - 전달받은 bot이 있으면 우선 사용
        if bot is not None:
            # 전달받은 bot과 websocket_logger 사용
            if websocket_logger is None:
                websocket_logger = WebSocketLogger(ticker, user_id)

            bot.logger = websocket_logger

            # scheduled_bots에서 사이클 카운트 업데이트 (있는 경우에만)
            if user_id in scheduled_bots and ticker in scheduled_bots[user_id]:
                bot_info = scheduled_bots[user_id][ticker]
                bot_info['cycle_count'] = bot_info.get('cycle_count', 0) + 1
                bot_info['last_run'] = datetime.now()
                cycle_count = bot_info['cycle_count']
            else:
                # 임시로 카운트 관리
                cycle_count = getattr(bot, '_cycle_count', 0) + 1
                bot._cycle_count = cycle_count

            websocket_logger.info(f"트레이딩 사이클 시작: {user_id}/{ticker} (#{cycle_count})")

            # 트레이딩 사이클 실행
            bot.run_cycle()

            websocket_logger.info(f"트레이딩 사이클 완료: {user_id}/{ticker}")
            return

        # 전달받은 bot이 없는 경우 저장된 봇 정보에서 가져오기
        if user_id not in scheduled_bots or ticker not in scheduled_bots[user_id]:
            logger.warning(f"스케줄된 봇 정보를 찾을 수 없음: {user_id}/{ticker}")
            return

        bot_info = scheduled_bots[user_id][ticker]
        bot = bot_info['bot']

        # 사이클 카운트 증가 (직접 접근)
        bot_info['cycle_count'] = bot_info.get('cycle_count', 0) + 1
        bot_info['last_run'] = datetime.now()

        # 웹소켓 로거 설정
        if websocket_logger is None:
            websocket_logger = WebSocketLogger(ticker, user_id)

        bot.logger = websocket_logger

        websocket_logger.info(f"트레이딩 사이클 시작: {user_id}/{ticker} (#{bot_info['cycle_count']})")

        # 트레이딩 사이클 실행
        bot.run_cycle()

        websocket_logger.info(f"트레이딩 사이클 완료: {user_id}/{ticker}")

    except Exception as e:
        logger.error(f"스케줄된 트레이딩 사이클 실행 중 오류: {user_id}/{ticker} - {str(e)}")

        # 오류 발생 시 봇 정리
        try:
            if user_id in scheduled_bots and ticker in scheduled_bots[user_id]:
                job_id = scheduled_bots[user_id][ticker].get('job_id')
                if job_id:
                    scheduler_manager.remove_job(job_id)
                del scheduled_bots[user_id][ticker]
                logger.info(f"오류로 인한 봇 정리: {user_id}/{ticker}")
        except Exception as cleanup_error:
            logger.error(f"봇 정리 중 오류: {cleanup_error}")


def create_trading_bot_from_favorite(favorite):
    """TradingFavorite 객체로부터 트레이딩 봇 생성"""
    try:
        from app.models import User
        from app.bot.trading_bot import UpbitTradingBot
        from app.api.upbit_api import UpbitAPI
        from app.utils.async_utils import AsyncHandler
        from app.utils.logging_utils import get_logger_with_current_date
        from app.strategy import create_strategy  # 올바른 함수 import

        # 사용자 정보 가져오기
        user = User.query.get(favorite.user_id)
        if not user:
            logger.error(f"사용자를 찾을 수 없음: {favorite.user_id}")
            return None

        # 업비트 API 키 확인
        if not user.upbit_access_key or not user.upbit_secret_key:
            logger.error(f"사용자 {favorite.user_id}의 업비트 API 키가 설정되지 않음")
            return None

        # 비동기 핸들러 생성
        async_handler = AsyncHandler()

        # 로거 생성
        bot_logger = get_logger_with_current_date(f"{favorite.user_id}_{favorite.ticker}")

        # API 객체 생성
        api = UpbitAPI(user.id, async_handler, bot_logger)

        # 봇 설정 생성 - 딕셔너리 형태로 전달하되 ticker 필드 확실히 포함
        settings = {
            'ticker': favorite.ticker,  # ticker 필드 명시적 추가
            'buy_amount': favorite.buy_amount,
            'min_cash': favorite.min_cash,
            'sell_portion': favorite.sell_portion,
            'prevent_loss_sale': favorite.prevent_loss_sale,
            'long_term_investment': favorite.long_term_investment,
            'window': favorite.window,
            'multiplier': favorite.multiplier,
            'buy_multiplier': favorite.buy_multiplier,
            'sell_multiplier': favorite.sell_multiplier,
            'k': favorite.k,
            'target_profit': favorite.target_profit,
            'stop_loss': favorite.stop_loss,
            'rsi_period': favorite.rsi_period,
            'rsi_oversold': favorite.rsi_oversold,
            'rsi_overbought': favorite.rsi_overbought,
            'rsi_timeframe': favorite.rsi_timeframe,
            'ensemble_volatility_weight': favorite.ensemble_volatility_weight,
            'ensemble_bollinger_weight': favorite.ensemble_bollinger_weight,
            'ensemble_rsi_weight': favorite.ensemble_rsi_weight,
            'interval': favorite.interval,
            'sleep_time': favorite.sleep_time,
            'user_id': favorite.user_id,
            'strategy': favorite.strategy,  # 전략 정보도 추가
            'name': favorite.name,
            'username': user.username
        }

        # 전략 객체 생성 - 올바른 함수명 사용
        strategy = create_strategy(favorite.strategy, api, bot_logger)
        if not strategy:
            logger.error(f"전략 생성 실패: {favorite.strategy}")
            return None

        # 봇 생성
        bot = UpbitTradingBot(settings, api, strategy, bot_logger, user.username)
        logger.info(f"봇 생성 성공: {favorite.name} ({favorite.ticker}) - User: {favorite.user_id}")
        return bot, settings

    except Exception as e:
        logger.error(f"봇 생성 중 오류: {e}")
        return None


# 자동매매 중지
@bp.route('/api/stop_bot/<ticker>', methods=['POST'])
@login_required
def stop_bot_route(ticker):
    """특정 티커의 봇 중지"""
    try:
        user_id = current_user.id
        success = stop_bot(user_id, ticker)

        if success:
            return jsonify({
                'status': 'success',
                'message': f'{ticker} 봇이 성공적으로 중지되었습니다.'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'{ticker} 봇 중지에 실패했습니다.'
            })
    except Exception as e:
        logger.error(f"봇 중지 오류: {e}")
        return jsonify({
            'status': 'error',
            'message': f'봇 중지 중 오류가 발생했습니다: {str(e)}'
        })


# 자동매매 중지
def stop_bot(user_id, ticker):
    """봇 중지 함수"""
    try:
        # 봇 정보 확인
        if user_id not in scheduled_bots:
            logger.warning(f"사용자 {user_id}의 봇 정보가 없습니다.")
            return False

        if ticker not in scheduled_bots[user_id]:
            logger.warning(f"봇 정보를 찾을 수 없음: {user_id}/{ticker}")
            return False

        bot_info = scheduled_bots[user_id][ticker]

        # 스케줄러 작업 중지
        job_id = bot_info.get('job_id')
        if job_id:
            try:
                scheduler_manager.remove_job(job_id)
                logger.info(f"스케줄러 작업 중지: {job_id}")
            except Exception as e:
                logger.warning(f"스케줄러 작업 중지 중 오류: {e}")

        # 봇 객체 중지
        bot = bot_info.get('bot')
        if bot:
            try:
                bot.is_running = False
                if hasattr(bot, 'stop_scheduled_trading'):
                    bot.stop_scheduled_trading()
                logger.info(f"봇 객체 중지: {user_id}/{ticker}")
            except Exception as e:
                logger.warning(f"봇 객체 중지 중 오류: {e}")

        # 봇 정보 삭제
        del scheduled_bots[user_id][ticker]

        # 사용자의 모든 봇이 중지되었다면 사용자 정보도 정리
        if not scheduled_bots[user_id]:
            del scheduled_bots[user_id]

        logger.info(f"봇 중지 완료: {user_id}/{ticker}")
        return True

    except Exception as e:
        logger.error(f"봇 중지 중 오류: {user_id}/{ticker} - {str(e)}")
        return False


# 선택 필드에서 라벨을 가져오기
def get_selected_label(value):
    """선택된 값에 대한 라벨 반환 - 수정된 함수"""
    # value가 정수(sleep_time)인 경우 처리
    if isinstance(value, int):
        if value < 60:
            return f"{value}초"
        elif value < 3600:
            minutes = value // 60
            return f"{minutes}분"
        else:
            hours = value // 3600
            return f"{hours}시간"

    # value가 form field인 경우 기존 로직
    if hasattr(value, 'choices'):
        try:
            for choice_value, label in value.choices:
                if choice_value == value.data:
                    return label
        except Exception as e:
            logger.error(f"get_selected_label: {e}")
            pass

    # 기본값 반환
    return str(value)


# ===== WebSocket 이벤트 핸들러를 별도 파일로 이동 =====
# 이 부분들은 websocket_handlers.py에서 처리됩니다.
# WebSocketLogger 클래스 부분 수정
class WebSocketLogger:
    def __init__(self, ticker, user_id):
        self.ticker = ticker
        self.user_id = user_id
        self.current_date = datetime.now().strftime('%Y%m%d')
        self._update_file_logger()

    def _update_file_logger(self):
        """파일 로거 업데이트 (날짜 변경 감지)"""
        from app.utils.logging_utils import get_logger_with_current_date
        self.file_logger = get_logger_with_current_date(self.ticker)

    def _check_date_change(self):
        """날짜 변경 확인 및 로거 업데이트"""
        today = datetime.now().strftime('%Y%m%d')
        if self.current_date != today:
            self.current_date = today
            self._update_file_logger()

    def _emit_log(self, level, message):
        # 날짜 변경 확인
        self._check_date_change()

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"[{timestamp}] [{level.upper()}] {message}"

        # 파일에 로그 기록
        if hasattr(self.file_logger, level.lower()):
            getattr(self.file_logger, level.lower())(message)

        # WebSocket을 통해 실시간 전송
        self._send_to_subscribers(formatted_message)

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


@bp.route('/api/active_tickers')
@login_required
def get_active_tickers():
    # 현재 사용자의 활성 티커 목록 반환
    user_id = current_user.id
    if user_id in scheduled_bots:
        tickers = list(scheduled_bots[user_id].keys())
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


# routes.py에 관리자 페이지
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


# 티커별 거래 기록 가져오는 API 엔드포인트 수정 dashboard 에서 필요함
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


# 즐겨찾기
@bp.route('/favorites')
@login_required
def favorites():
    favorites = TradingFavorite.query.filter_by(user_id=current_user.id).order_by(TradingFavorite.created_at.desc()).all()
    return render_template('favorites.html', title='즐겨찾기', favorites=favorites)


# 자동재시작 토글
@bp.route('/toggle_auto_restart/<int:favorite_id>', methods=['POST'])
@login_required
def toggle_auto_restart(favorite_id):
    """자동 재시작 토글"""
    favorite = TradingFavorite.query.filter_by(id=favorite_id, user_id=current_user.id).first()
    if not favorite:
        return jsonify({'success': False, 'message': '즐겨찾기를 찾을 수 없습니다.'}), 404

    try:
        # start_yn 값 토글
        new_status = 'N' if favorite.start_yn == 'Y' else 'Y'
        favorite.start_yn = new_status
        favorite.updated_at = datetime.now()

        db.session.commit()

        status_text = 'Y' if new_status == 'Y' else 'N'
        message = f'자동 재시작이 {"활성화" if new_status == "Y" else "비활성화"}되었습니다.'

        return jsonify({
            'success': True,
            'message': message,
            'status': status_text,
            'new_status': new_status
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'오류가 발생했습니다: {str(e)}'}), 500


def auto_save_favorite_from_settings(form_data):
    """settings에서 자동으로 즐겨찾기 저장"""
    try:
        from app.models import TradingFavorite, db
        from datetime import datetime

        # 자동 생성된 이름 (타임스탬프 포함)
        favorite_name = form_data.get('favorite_name', '').strip()
        if form_data.get('favorite_start_yn') == 'true':
            start_yn = 'Y'
        else:
            start_yn = 'N'

        # 중복 이름 확인
        existing = TradingFavorite.query.filter_by(
            user_id=current_user.id,
            name=favorite_name
        ).first()

        if existing:
            favorite_name += f"_{datetime.now().strftime('%S')}"  # 초까지 추가

        # 즐겨찾기 객체 생성 (save_favorite 로직 활용)
        favorite_data = {
            'name': favorite_name,
            'ticker': form_data.get('ticker'),
            'strategy': form_data.get('strategy'),
            'interval': form_data.get('interval'),
            'buy_amount': form_data.get('buy_amount'),
            'min_cash': form_data.get('min_cash'),
            'sleep_time': form_data.get('sleep_time'),
            'sell_portion': form_data.get('sell_portion'),
            'prevent_loss_sale': form_data.get('prevent_loss_sale'),
            'long_term_investment': form_data.get('long_term_investment'),
            'window': form_data.get('window'),
            'multiplier': form_data.get('multiplier'),
            'buy_multiplier': form_data.get('buy_multiplier'),
            'sell_multiplier': form_data.get('sell_multiplier'),
            'k': form_data.get('k'),
            'target_profit': form_data.get('target_profit'),
            'stop_loss': form_data.get('stop_loss'),
            'rsi_period': form_data.get('rsi_period'),
            'rsi_oversold': form_data.get('rsi_oversold'),
            'rsi_overbought': form_data.get('rsi_overbought'),
            'rsi_timeframe': form_data.get('rsi_timeframe'),
            'ensemble_volatility_weight': form_data.get('ensemble_volatility_weight'),
            'ensemble_bollinger_weight': form_data.get('ensemble_bollinger_weight'),
            'ensemble_rsi_weight': form_data.get('ensemble_rsi_weight'),
            'start_yn': start_yn
        }

        # save_favorite의 핵심 로직 재사용
        result = save_favorite_data(favorite_data)
        return result

    except Exception as e:
        logger.error(f"자동 즐겨찾기 저장 오류: {e}")
        return {'success': False, 'error': str(e)}


def save_favorite_data(favorite_data):
    """즐겨찾기 데이터 저장 (공통 함수)"""
    global db
    try:
        from app.models import TradingFavorite, db

        favorite = TradingFavorite(
            user_id=current_user.id,
            name=favorite_data['name'],
            ticker=favorite_data['ticker'],
            strategy=favorite_data['strategy'],
            interval=favorite_data['interval'],
            buy_amount=float(favorite_data['buy_amount']),
            min_cash=float(favorite_data['min_cash']),
            sleep_time=int(favorite_data['sleep_time']),
            sell_portion=float(favorite_data['sell_portion']),
            prevent_loss_sale=favorite_data['prevent_loss_sale'],
            long_term_investment=favorite_data['long_term_investment'],
            window=int(favorite_data['window']),
            multiplier=float(favorite_data['multiplier']),
            # 비대칭 볼린저 밴드 필드 추가
            buy_multiplier=float(favorite_data['buy_multiplier']) if favorite_data.get('buy_multiplier') else None,
            sell_multiplier=float(favorite_data['sell_multiplier']) if favorite_data.get('sell_multiplier') else None,
            k=float(favorite_data['k']),
            target_profit=float(favorite_data['target_profit']),
            stop_loss=float(favorite_data['stop_loss']),
            rsi_period=int(favorite_data['rsi_period']),
            rsi_oversold=float(favorite_data['rsi_oversold']),
            rsi_overbought=float(favorite_data['rsi_overbought']),
            rsi_timeframe=favorite_data['rsi_timeframe'],
            ensemble_volatility_weight=float(favorite_data['ensemble_volatility_weight']),
            ensemble_bollinger_weight=float(favorite_data['ensemble_bollinger_weight']),
            ensemble_rsi_weight=float(favorite_data['ensemble_rsi_weight']),
            start_yn=favorite_data['start_yn'],
            created_at=datetime.now()
        )
        # print(favorite.)

        db.session.add(favorite)
        db.session.commit()

        return {
            'success': True,
            'name': favorite_data['name'],
            'message': '즐겨찾기가 저장되었습니다.'
        }

    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }

# 즐겨찾기 저장
# 즐겨찾기 저장
@bp.route('/save_favorite', methods=['POST'])
@login_required
def save_favorite():
    settings_form = TradingSettingsForm(request.form)
    favorite_form = FavoriteForm(request.form)

    if favorite_form.name.data:
        # 체크박스 값을 Y/N으로 변환
        start_yn = 'Y' if favorite_form.start_yn.data else 'N'

        favorite = TradingFavorite(
            user_id=current_user.id,
            name=favorite_form.name.data,
            start_yn=start_yn
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


# 즐겨찾기 삭제
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


@bp.route('/admin/monitor')
@login_required
def admin_monitor():
    """관리자 모니터링 대시보드"""
    if not current_user.is_admin:
        flash('관리자 권한이 필요합니다.', 'danger')
        return redirect(url_for('main.index'))

    return render_template('admin/monitor_dashboard.html')


@bp.route('/api/scheduler/status')
@login_required
def get_scheduler_status():
    """모든 사용자의 스케줄러 상태 조회"""
    try:
        # 모든 사용자의 봇 정보를 조회
        all_user_bots = []

        # get_jobs() 대신 get_all_jobs() 사용
        all_jobs = scheduler_manager.get_all_jobs()

        status = {
            'scheduler_running': scheduler_manager.is_started(),
            'total_jobs': len(all_jobs),
            'all_user_bots': []
        }

        # scheduled_bots의 모든 사용자 정보 순회
        for user_id, user_bots in scheduled_bots.items():
            user_bot_list = []
            user_total_investment = 0
            user_total_current_value = 0
            user_portfolio_info = {}

            # print(f"scheduled_bots[{user_id}] = {user_bots}")

            for ticker, bot_info in user_bots.items():
                job_id = bot_info.get('job_id')
                formdata = bot_info.get('settings')  # 딕셔너리 형태의 settings
                # print(f"bot_info: {bot_info}, formdata: {formdata}")

                job_info_from_scheduler = scheduler_manager.get_job_info(job_id) if job_id else None

                # APScheduler에서 직접 job 가져오기
                job = None
                if job_id and scheduler_manager.scheduler:
                    try:
                        job = scheduler_manager.scheduler.get_job(job_id)
                    except:
                        job = None

                # settings에서 값 안전하게 가져오기
                def get_setting_value(key, default=None):
                    if formdata and isinstance(formdata, dict):
                        return formdata.get(key, default)
                    elif formdata and hasattr(formdata, key):
                        field = getattr(formdata, key)
                        return field.data if hasattr(field, 'data') else field
                    return default

                # 현재가 및 포트폴리오 정보 가져오기 (업비트 API 사용)
                try:
                    user = User.query.filter_by(id=user_id).first()
                    if user:
                        # User 모델에서 암호화된 API 키 복호화
                        access_key, secret_key = user.get_upbit_keys()

                        if access_key and secret_key:
                            # UpbitAPI 클래스를 user_id로 초기화하는 방식 사용
                            upbit_api = UpbitAPI.create_from_user(user, async_handler, logger)

                            # 현재가 조회 - 단일 ticker로 호출하여 float 값 반환
                            current_price = upbit_api.get_current_price(ticker)
                            current_price = float(current_price) if current_price else 0

                            # 보유 코인 정보 조회 - get_balances 메서드 사용 (iterable 반환)
                            balances = upbit_api.upbit.get_balances()
                            coin_currency = ticker.split('-')[1]  # KRW-BTC -> BTC

                            coin_balance = 0
                            avg_buy_price = 0
                            if balances:
                                for balance in balances:
                                    if balance['currency'] == coin_currency:
                                        coin_balance = float(balance['balance'])
                                        avg_buy_price = float(balance['avg_buy_price'])
                                        break

                            # 현재 보유 가치 계산 (현재 투자된 ticker들의 평가금액)
                            current_value = coin_balance * current_price
                            # user_total_current_value += current_value

                            # 수익률 계산
                            profit_rate = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0

                            # 포트폴리오 정보 저장
                            user_portfolio_info[ticker] = {
                                'coin_balance': coin_balance,
                                'avg_buy_price': avg_buy_price,
                                'current_price': current_price,
                                'current_value': current_value,
                                'profit_rate': profit_rate
                            }
                        else:
                            # API 키가 없는 경우 기본값 설정
                            user_portfolio_info[ticker] = {
                                'coin_balance': 0,
                                'avg_buy_price': 0,
                                'current_price': 0,
                                'current_value': 0,
                                'profit_rate': 0
                            }

                except Exception as e:
                    logger.error(f"투자 정보 조회 중 오류 (사용자: {user_id}, 티커: {ticker}): {str(e)}")
                    # 오류 발생 시 기본값 설정
                    user_portfolio_info[ticker] = {
                        'coin_balance': 0,
                        'avg_buy_price': 0,
                        'current_price': 0,
                        'current_value': 0,
                        'profit_rate': 0
                    }

                bot_status = {
                    'ticker': ticker,
                    'strategy': bot_info.get('strategy', 'Unknown'),
                    'start_time': bot_info.get('start_time', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                    'cycle_count': bot_info.get('cycle_count', 0),
                    'last_run': bot_info.get('last_run', datetime.now()).strftime('%Y-%m-%d %H:%M:%S') if bot_info.get('last_run') else 'Never',
                    'next_run': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job and job.next_run_time else 'Unknown',
                    'job_id': job_id,
                    'running': job is not None,
                    'interval': bot_info.get('interval', 0),
                    'run_count': job_info_from_scheduler.get('run_count', 0) if job_info_from_scheduler else 0,
                    'username': bot_info.get('username', 'Unknown'),
                    'interval_label': bot_info.get('interval_label', 'Unknown'),
                    'buy_amount': get_setting_value('buy_amount', 0),
                    'window': get_setting_value('window', 20),
                    'multiplier': get_setting_value('multiplier', 2.0),
                    'buy_multiplier': get_setting_value('buy_multiplier', 3.0),
                    'sell_multiplier': get_setting_value('sell_multiplier', 2.0),
                    'long_term_investment': bot_info.get('long_term_investment', 'N'),
                    # 투자 정보 추가
                    'portfolio_info': user_portfolio_info.get(ticker, {
                        'coin_balance': 0,
                        'avg_buy_price': 0,
                        'current_price': 0,
                        'current_value': 0,
                        'profit_rate': 0
                    })
                }

                user_bot_list.append(bot_status)

            # 사용자 username 가져오기
            user = User.query.filter_by(id=user_id).first()
            user_name = user.username if user else None

            # 현금 보유량 조회 (get_balance_cash 메서드 직접 사용 - float 반환)
            krw_balance = 0
            try:
                if user:
                    # User 모델에서 암호화된 API 키 복호화
                    access_key, secret_key = user.get_upbit_keys()

                    if access_key and secret_key:
                        upbit_api = UpbitAPI.create_from_user(user, async_handler, logger)
                        # get_balance_cash는 float 값을 직접 반환
                        krw_balance = upbit_api.get_balance_cash()
                        krw_balance = float(krw_balance) if krw_balance else 0
                        balances = upbit_api.upbit.get_balances()

                        if balances:
                            for balance in balances:
                                if balance['currency'] != 'KRW':
                                    user_total_current_value += float(balance['balance']) * float(upbit_api.get_current_price(f'KRW-{balance['currency']}'))
                                    user_total_investment += float(balance['balance']) * float(balance['avg_buy_price'])

            except Exception as e:
                logger.error(f"현금 보유량 조회 중 오류 (사용자: {user_id}): {str(e)}")

            # 계산 수정: 요구사항에 따른 정확한 계산
            # 총 금액: 전체 투자 및 보유금액의 합 (투자한 금액 + 보유 현금)
            total_investment_amount = user_total_investment + krw_balance

            # 보유현금: 전체 투자 금액에서 투자한 금액을 뺀 값 (이미 krw_balance로 계산됨)
            cash_balance = krw_balance

            # 손익: 현재 평가금액 - 투자금액
            profit_loss = user_total_current_value - user_total_investment

            # 수익률: 손익에 대한 백분율
            total_profit_rate = 0
            if user_total_investment > 0:
                total_profit_rate = (profit_loss / user_total_investment * 100)

            # 사용자별 봇 정보 추가
            if user_bot_list:  # 봇이 있는 사용자만 추가
                user_info = {
                    'user_id': user_id,
                    'user_name': user_name,
                    'bot_count': len(user_bot_list),
                    'bots': user_bot_list,
                    # 투자 정보 수정
                    'investment_info': {
                        'total_investment': total_investment_amount,  # 총 투자금액: 전체 투자 + 보유금액의 합
                        'current_value': user_total_current_value,  # 현재 평가금액: 현재 투자된 ticker들의 합
                        'krw_balance': cash_balance,  # 보유현금: 전체 투자 금액에서 투자한 금액을 뺀 값
                        'profit_loss': profit_loss,  # 손익: 현재 평가금액 - 투자금액
                        'total_profit_rate': total_profit_rate  # 수익률: 손익에 대한 백분율
                    }
                }
                status['all_user_bots'].append(user_info)

        return jsonify(status)

    except Exception as e:
        logger.error(f"모든 사용자의 스케줄러 상태 조회 중 오류: {str(e)}")
        return jsonify({'error': str(e)}), 500