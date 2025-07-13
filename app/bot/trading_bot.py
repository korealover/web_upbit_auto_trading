from flask_login import current_user
from app.utils.scheduler_manager import scheduler_manager

from app.utils.telegram_utils import TelegramNotifier
try:
    from app.utils.thread_monitor import thread_monitor, monitor_trading_thread
    THREAD_MONITOR_AVAILABLE = True
except ImportError:
    THREAD_MONITOR_AVAILABLE = False
    # 더미 클래스와 데코레이터
    class DummyThreadMonitor:
        def register_thread(self, **kwargs):
            pass
        def unregister_thread(self, **kwargs):
            pass
        def monitor_thread_context(self, **kwargs):
            from contextlib import nullcontext
            return nullcontext()
    
    thread_monitor = DummyThreadMonitor()
    def monitor_trading_thread(**kwargs):
        def decorator(func):
            return func
        return decorator

from config import Config
from app.models import TradeRecord
from app import db
import datetime
import time
import threading
from app.utils.shared import trading_bots, lock  # 공유 자원 가져오기
shutdown_event = threading.Event()  # 글로벌 종료 이벤트 정의

class UpbitTradingBot:
    """업비트 자동 거래 봇 클래스"""

    def __init__(self, args, upbit_api, strategy, logger, username=None):
        """초기화"""
        self.args = args
        self.api = upbit_api
        self.strategy = strategy
        self.logger = logger
        self.username = username
        self.job_id = None
        self.is_running = False

        # 사용자 ID 확인 및 저장
        self.user_id = None
        if hasattr(args, 'user_id'):
            self.user_id = args.user_id
            self.logger.info(f"봇 초기화: 사용자 ID {self.user_id} (객체 속성)")
        elif isinstance(args, dict) and 'user_id' in args:
            self.user_id = args['user_id']
            self.logger.info(f"봇 초기화: 사용자 ID {self.user_id} (딕셔너리)")

        # 텔레그램 알림 초기화
        self.telegram_enabled = Config.TELEGRAM_NOTIFICATIONS_ENABLED
        if self.telegram_enabled and Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
            self.telegram = TelegramNotifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID, logger, self.username)
            self.logger.info("텔레그램 알림 기능 활성화됨")
        else:
            self.telegram = None
            if self.telegram_enabled:
                self.logger.warning("텔레그램 알림 기능이 활성화되었지만, 봇 토큰 또는 채팅 ID가 설정되지 않았습니다.")
                self.telegram_enabled = False

    def send_trade_notification(self, trade_type, ticker, order_result):
        """거래 알림 전송"""
        if not self.telegram_enabled or not self.telegram:
            return

        try:
            if trade_type == 'BUY':
                # 매수 알림
                amount = float(order_result.get('price', 0))
                price = self.api.get_current_price(ticker)
                volume = float(order_result.get('volume', 0))
                self.telegram.send_trade_message('매수', ticker, amount, price, volume)
            elif trade_type == 'SELL':
                # 매도 알림
                volume = float(order_result.get('volume', 0))
                price = self.api.get_current_price(ticker)
                amount = price * volume if price and volume else 0
                self.telegram.send_trade_message('매도', ticker, volume, price, amount)
        except Exception as e:
            self.logger.error(f"텔레그램 거래 알림 전송 중 오류: {str(e)}")

    def _get_field_value(self, field, default=None):
        """WTForms 필드에서 안전하게 값 추출"""
        try:
            if hasattr(field, 'data'):
                return field.data
            elif isinstance(field, dict):
                return field.get('data', default)
            else:
                return field if field is not None else default
        except Exception as e:
            self.logger.warning(f"필드 값 추출 중 오류: {e}")
            return default

    def trading(self):
        """트레이딩 로직 실행"""
        try:
            # 스레드 모니터링 등록 (사용 가능한 경우만)
            if THREAD_MONITOR_AVAILABLE:
                ticker_value = self._get_field_value(getattr(self.args, 'ticker', None))
                strategy_value = self._get_field_value(getattr(self.args, 'strategy', None))
                
                thread_monitor.register_thread(
                    user_id=self.username,
                    ticker=ticker_value,
                    strategy=strategy_value
                )

            # 필드 값들을 안전하게 추출
            ticker = self._get_field_value(getattr(self.args, 'ticker', None))
            buy_amount = self._get_field_value(getattr(self.args, 'buy_amount', None))
            min_cash = self._get_field_value(getattr(self.args, 'min_cash', None))
            prevent_loss_sale = self._get_field_value(getattr(self.args, 'prevent_loss_sale', None), 'N')

            if not ticker:
                self.logger.error("티커 정보를 가져올 수 없습니다.")
                return None

            # 전략에 따라 분기
            strategy_name = self._get_field_value(getattr(self.args, 'strategy', None))
            
            if strategy_name == 'volatility':
                # 변동성 돌파 전략 사용
                self.logger.info(f"변동성 돌파 전략으로 거래 분석 시작: {ticker}")
                k_value = self._get_field_value(getattr(self.args, 'k', None))
                target_profit = self._get_field_value(getattr(self.args, 'target_profit', None))
                stop_loss = self._get_field_value(getattr(self.args, 'stop_loss', None))
                signal = self.strategy.generate_volatility_signal(ticker, k_value, target_profit, stop_loss)
                
            elif strategy_name == 'adaptive':
                # 어댑티브 전략 사용
                self.logger.info(f"어댑티브 전략으로 거래 분석 시작: {ticker}")
                signal = self.strategy.generate_signal(ticker)
                
            elif strategy_name == 'ensemble':
                # 앙상블 전략 사용
                self.logger.info(f"앙상블 전략으로 거래 분석 시작: {ticker}")
                signal = self.strategy.generate_signal(ticker)
                
            elif strategy_name == 'rsi':
                # RSI 전략 사용
                self.logger.info(f"RSI 전략으로 거래 분석 시작: {ticker}")
                rsi_period = self._get_field_value(getattr(self.args, 'rsi_period', None))
                rsi_oversold = self._get_field_value(getattr(self.args, 'rsi_oversold', None))
                rsi_overbought = self._get_field_value(getattr(self.args, 'rsi_overbought', None))
                rsi_timeframe = self._get_field_value(getattr(self.args, 'rsi_timeframe', None))
                signal = self.strategy.generate_signal(ticker, rsi_period, rsi_oversold, rsi_overbought, rsi_timeframe)
                
            else:
                # 볼린저 밴드 전략 사용 (기본값)
                interval = self._get_field_value(getattr(self.args, 'interval', None))
                window = self._get_field_value(getattr(self.args, 'window', None))
                multiplier = self._get_field_value(getattr(self.args, 'multiplier', None))

                self.logger.info(f"볼린저 밴드 전략으로 거래 분석 시작: {ticker}, 간격: {interval}")

                # OHLCV 데이터 가져오기
                prices_data = self.api.get_ohlcv_data(ticker, interval, window + 5)  # 여유있게 가져옴

                if prices_data is None or len(prices_data) < window:
                    self.logger.error(f"가격 데이터를 충분히 가져오지 못했습니다. 받은 데이터 수: {0 if prices_data is None else len(prices_data)}")
                    return None

                # 종가 데이터만 추출
                prices = prices_data['close']

                # 매매 신호 생성 (볼린저 밴드 전략에 맞는 매개변수 전달)
                signal = self.strategy.generate_signal(ticker, prices, window, multiplier)

            # 잔고 조회
            balance_cash = self.api.get_balance_cash()
            balance_coin = self.api.get_balance_coin(ticker)

            # 잔고 정보 로깅
            if balance_cash is not None:
                self.logger.info(f"보유 현금: {balance_cash:,.2f}원")

            if balance_coin is not None and balance_coin > 0:
                avg_price = self.api.get_buy_avg(ticker)
                current_price = self.api.get_current_price(ticker)

                if avg_price and current_price:
                    profit_loss = (current_price - avg_price) / avg_price * 100
                    value = balance_coin * current_price
                    self.logger.info(f"보유 {ticker}: {balance_coin} (평균가: {avg_price:,.2f}, 현재가치: {value:,.2f}원, 수익률: {profit_loss:.2f}%)")

            # 매매 신호에 따른 주문 처리
            if signal == 'BUY' and balance_cash and balance_cash > min_cash:
                self.logger.info(f"매수 시그널 발생: {buy_amount:,.2f}원 매수 시도")
                order_result = self.api.order_buy_market(ticker, buy_amount)

                # 매수 완료 텔레그램 알림 전송
                if order_result and not isinstance(order_result, int) and 'error' not in order_result:
                    # 주문 UUID 추출
                    order_uuid = order_result.get('uuid')
                    self.logger.info(f"매수 주문 접수됨, UUID: {order_uuid}")

                    # 거래 체결 확인을 위해 잠시 대기
                    time.sleep(2)

                    # 현재 시장 가격 조회
                    current_price = self.api.get_current_price(ticker)

                    # 주문 후 실제 잔고 변화 확인
                    before_coin = balance_coin or 0
                    after_coin = self.api.get_balance_coin(ticker) or 0

                    # 실제 매수된 수량 계산
                    actual_volume = after_coin - before_coin

                    if actual_volume > 0:
                        self.logger.info(f"매수 체결 확인: {actual_volume} {ticker.split('-')[1]} 매수됨")

                        # 매수 금액 (실제 지불한 금액)
                        amount = buy_amount  # 주문 금액 사용

                        # 텔레그램 알림 전송
                        self.send_trade_notification('BUY', ticker, {
                            'price': amount,
                            'volume': actual_volume
                        })

                        # 거래 기록 저장
                        self.record_trade('BUY', ticker, current_price, actual_volume, amount)
                    else:
                        self.logger.warning(f"매수 주문이 접수되었으나 아직 체결되지 않았습니다. UUID: {order_uuid}")

                        # 체결되지 않은 경우, 예상 수량으로 기록
                        estimated_volume = buy_amount / current_price if current_price else 0
                        self.logger.info(f"예상 매수 수량: {estimated_volume} (현재가 기준)")

                        # 거래 기록 저장 (예상 수량 사용)
                        self.record_trade('BUY', ticker, current_price, estimated_volume, buy_amount)

                return order_result
            elif signal == 'SELL' and balance_coin and balance_coin > 0:
                self.logger.info(f"매도 시그널 발생: {balance_coin} {ticker.split('-')[1]} 매도 시도")

                # 현재가 조회하여 보유 코인 가치 확인
                current_price = self.api.get_current_price(ticker)
                if not current_price:
                    self.logger.error("현재가를 조회할 수 없어 매도를 건너뜁니다.")
                    return None

                avg_buy_price = self.api.get_buy_avg(ticker)  # 평단가를 미리 조회

                # 손절 금지 설정을 확인하여 매도를 건너뜁니다. (기본값: Y) 최소 0.001%는 먹자(0.0005%는 수수료를 주니까)
                if prevent_loss_sale == 'Y' and avg_buy_price and current_price < (avg_buy_price * 1.001):
                    self.logger.info(f"손절 금지 설정됨. 현재가({current_price}) < 평균 단가({avg_buy_price}). 매도하지 않습니다.")
                    return None

                if current_price:
                    total_value = balance_coin * current_price
                    self.logger.info(f"현재 보유 코인 총 가치: {total_value:,.2f}원")

                    # 전체 가치가 5,000원 미만인 경우 경고
                    if total_value < 5000:
                        self.logger.warning(f"보유 코인 총 가치({total_value:,.2f}원)가 최소 주문 금액(5,000원) 미만입니다. 매도를 건너뜁니다.")
                        return None

                # 분할 매도 처리
                sell_portion = self._get_field_value(getattr(self.args, 'sell_portion', None), 1.0)

                # 매도 전략 결정
                if sell_portion < 1.0:
                    self.logger.info(f"분할 매도 시도: 보유량의 {sell_portion * 100:.1f}% 매도")
                    order_result = self.api.order_sell_market_partial(ticker, sell_portion)

                    # 분할 매도에서 오류가 발생한 경우 처리
                    if order_result and 'error' in order_result:
                        error_name = order_result['error'].get('name', '')

                        if error_name == 'insufficient_total_value':
                            self.logger.warning("보유 코인 가치가 부족하여 매도를 건너뜁니다.")
                            return None
                        elif error_name == 'too_small_volume':
                            self.logger.warning("매도 수량이 너무 적어 전량 매도로 전환합니다.")
                            # 전량 매도로 재시도
                            order_result = self.api.order_sell_market(ticker, balance_coin)
                        else:
                            self.logger.error(f"분할 매도 오류: {order_result['error']['message']}")
                            return None
                else:
                    self.logger.info(f"전량 매도 시도: {balance_coin} {ticker.split('-')[1]}")
                    order_result = self.api.order_sell_market(ticker, balance_coin)

                # 매도 완료 텔레그램 알림 전송
                if order_result and not isinstance(order_result, int) and 'error' not in order_result:
                    # 주문 UUID 추출
                    order_uuid = order_result.get('uuid')
                    self.logger.info(f"매도 주문 접수됨, UUID: {order_uuid}")

                    # 거래 체결 확인을 위해 잠시 대기
                    time.sleep(2)

                    # 현재 가격 조회
                    current_price = self.api.get_current_price(ticker)

                    # 실제 매도된 수량 계산
                    if 'actual_sell_portion' in order_result:
                        # 분할 매도에서 조정된 비율 사용
                        actual_portion = order_result['actual_sell_portion']
                        volume = balance_coin * actual_portion
                        self.logger.info(f"실제 매도된 비율: {actual_portion * 100:.1f}% (원래 계획: {sell_portion * 100:.1f}%)")
                    elif sell_portion < 1.0:
                        volume = balance_coin * sell_portion
                    else:
                        volume = balance_coin

                    # 매도 금액 계산
                    amount = volume * current_price if current_price else 0

                    # 텔레그램 알림 전송
                    self.send_trade_notification('SELL', ticker, {
                        'volume': volume
                    })

                    # 평균 매수가 조회 및 수익률 계산
                    avg_buy_price = self.api.get_buy_avg(ticker)
                    profit_loss = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price else None

                    # 거래 기록 저장
                    self.record_trade('SELL', ticker, current_price, volume, amount, profit_loss)

                return order_result
            else:
                self.logger.info("포지션 유지 (매수/매도 조건 불충족)")

        except Exception as e:
            self.logger.error(f"거래 중 오류 발생: {str(e)}", exc_info=True)

        return None

    def run_cycle(self):
        """거래 사이클 실행"""
        try:
            if shutdown_event.is_set():
                self.logger.info("종료 신호를 받았습니다. 거래 사이클을 중단합니다.")
                return

            self.logger.info("=" * 20 + f" 거래자 ID : {self.username} " + "=" * 20)
            ticker = self._get_field_value(getattr(self.args, 'ticker', None), 'Unknown')
            self.logger.info(f"거래 사이클 시작: {ticker}")

            # 트레이딩 실행
            ret = self.trading()

            if ret:
                self.logger.info(f"거래 결과: {ret}")

            self.logger.info(f"거래 사이클 종료: {ticker}")
            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"실행 중 오류 발생: {str(e)}", exc_info=True)

    def record_trade(self, trade_type, ticker, price, volume, amount, profit_loss=None):
        """거래 기록 저장"""
        try:
            # Flask 애플리케이션 컨텍스트를 정확하게 가져오기
            from app import create_app

            # 현재 앱 인스턴스 가져오기 또는 새로 생성
            try:
                from flask import current_app
                app = current_app._get_current_object()
            except RuntimeError:
                # 현재 앱 컨텍스트가 없는 경우 새로 생성
                app = create_app()

            with app.app_context():
                from app.models import TradeRecord, db
                from app.models import kst_now  # 한국 시간 함수 import

                # 매도인 경우 수익/손실률 계산
                if trade_type == 'SELL':
                    try:
                        # 평균 매수가 가져오기
                        avg_buy_price = self.api.get_buy_avg(ticker)
                        if avg_buy_price and avg_buy_price > 0:
                            profit_loss = ((price - avg_buy_price) / avg_buy_price) * 100
                            self.logger.info(f"수익률 계산: 매도가({price}) - 평균매수가({avg_buy_price}) = {profit_loss:.2f}%")
                    except Exception as e:
                        self.logger.warning(f"수익률 계산 실패: {str(e)}")

                # 전략 이름 안전하게 가져오기
                strategy_name = self._get_field_value(getattr(self.args, 'strategy', None), 'unknown')

                # TradeRecord 생성 및 저장
                trade_record = TradeRecord(
                    user_id=self.user_id,
                    ticker=ticker,
                    trade_type=trade_type,
                    price=price,
                    volume=volume,
                    amount=amount,
                    profit_loss=profit_loss,
                    strategy=strategy_name,
                    timestamp=kst_now()  # UTC 대신 한국 시간 사용
                )

                db.session.add(trade_record)
                db.session.commit()

                self.logger.info(f"거래 기록 저장 완료: {trade_type} {ticker} {volume} @ {price}")

        except Exception as e:
            self.logger.error(f"거래 기록 저장 중 오류: {str(e)}")
            import traceback
            self.logger.error(f"상세 오류: {traceback.format_exc()}")

    def start_scheduled_trading(self, interval_seconds=None):
        """스케줄링된 트레이딩 시작"""
        if self.is_running:
            self.logger.warning("이미 실행 중인 트레이딩 봇입니다.")
            return False

        # 간격 설정 (기본값: args에서 가져오기)
        if interval_seconds is None:
            interval_seconds = self._get_field_value(getattr(self.args, 'sleep_time', None), 30)

        # 작업 ID 생성
        ticker = self._get_field_value(getattr(self.args, 'ticker', None))
        strategy = self._get_field_value(getattr(self.args, 'strategy', None))
        self.job_id = f"{self.username}_{ticker}_{strategy}_{int(datetime.now().timestamp())}"

        # 스케줄러에 작업 추가
        success = scheduler_manager.add_trading_job(
            job_id=self.job_id,
            trading_func=self._scheduled_trading_cycle,
            interval_seconds=interval_seconds,
            user_id=self.username,
            ticker=ticker,
            strategy=strategy
        )

        if success:
            self.is_running = True
            self.logger.info(f"스케줄링된 트레이딩 시작: {self.job_id}")
            return True
        else:
            self.logger.error("스케줄링된 트레이딩 시작 실패")
            return False

    def stop_scheduled_trading(self):
        """스케줄링된 트레이딩 중지"""
        if not self.is_running or not self.job_id:
            return False

        success = scheduler_manager.remove_job(self.job_id)
        if success:
            self.is_running = False
            self.logger.info(f"스케줄링된 트레이딩 중지: {self.job_id}")
            return True
        else:
            self.logger.error("스케줄링된 트레이딩 중지 실패")
            return False

    def _scheduled_trading_cycle(self):
        """스케줄러에서 호출되는 트레이딩 사이클"""
        try:
            # 작업 실행 횟수 업데이트
            if self.job_id and self.job_id in scheduler_manager.active_jobs:
                job_info = scheduler_manager.active_jobs[self.job_id]
                job_info['run_count'] += 1
                job_info['last_run'] = datetime.now()

            # 기존 trading() 메서드 호출
            self.trading()

        except Exception as e:
            self.logger.error(f"스케줄링된 트레이딩 사이클 실행 중 오류: {e}", exc_info=True)

