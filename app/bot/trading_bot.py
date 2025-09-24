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
        """폼 필드나 딕셔너리 값을 안전하게 추출"""
        if field is None:
            return default

        # WTForms 필드인 경우
        if hasattr(field, 'data'):
            value = field.data
        else:
            # 일반 값인 경우
            value = field

        # 문자열인 경우 정수로 변환 시도
        if isinstance(value, str) and value.isdigit():
            try:
                return int(value)
            except ValueError:
                return default

        return value

    def calculate_dynamic_sleep_time(self, ticker, base_sleep_time):
        """변동성 기반 동적 거래 간격 계산"""
        try:
            # 최근 1시간 데이터로 변동성 계산
            df = self.api.get_ohlcv_data(ticker, 'minute5', 12)  # 5분봉 12개 = 1시간
            if df is None or len(df) < 2:
                return base_sleep_time

            # 변동성 계산 (표준편차)
            price_changes = df['close'].pct_change().dropna()
            volatility = price_changes.std()

            # 변동성에 따른 간격 조정
            if volatility > 0.02:  # 높은 변동성 (2% 이상)
                adjusted_time = max(30, base_sleep_time * 0.5)  # 최소 30초
                self.logger.info(f"높은 변동성 감지 ({volatility:.4f}), 거래간격 단축: {adjusted_time}초")
            elif volatility < 0.005:  # 낮은 변동성 (0.5% 미만)
                adjusted_time = min(300, base_sleep_time * 2)  # 최대 5분
                self.logger.info(f"낮은 변동성 감지 ({volatility:.4f}), 거래간격 연장: {adjusted_time}초")
            else:
                adjusted_time = base_sleep_time

            return int(adjusted_time)
        except Exception as e:
            self.logger.error(f"동적 거래간격 계산 오류: {e}")
            return base_sleep_time

    def calculate_volatility_based_position_size(self, ticker, base_amount):
        """변동성 기반 포지션 사이징"""
        try:
            # 최근 24시간 데이터로 변동성 계산
            df = self.api.get_ohlcv_data(ticker, 'minute60', 24)  # 1시간봉 24개 = 24시간
            if df is None or len(df) < 2:
                return base_amount

            # 일일 변동성 계산
            price_changes = df['close'].pct_change().dropna()
            daily_volatility = price_changes.std() * (24 ** 0.5)  # 일일 변동성으로 스케일링

            # 변동성에 따른 포지션 사이즈 조정
            if daily_volatility > 0.1:  # 높은 변동성 (10% 이상)
                position_multiplier = 0.7  # 포지션 크기 축소
                self.logger.info(f"높은 일일 변동성 ({daily_volatility:.4f}), 포지션 크기 축소")
            elif daily_volatility < 0.03:  # 낮은 변동성 (3% 미만)
                position_multiplier = 1.3  # 포지션 크기 확대
                self.logger.info(f"낮은 일일 변동성 ({daily_volatility:.4f}), 포지션 크기 확대")
            else:
                position_multiplier = 1.0

            adjusted_amount = int(base_amount * position_multiplier)
            return max(5000, min(50000, adjusted_amount))  # 최소 5천원, 최대 5만원
        except Exception as e:
            self.logger.error(f"변동성 기반 포지션 사이징 오류: {e}")
            return base_amount

    def check_profit_loss_management(self, ticker, balance_coin):
        """손익 관리 기능 - 손절/익절 체크"""
        try:
            if not balance_coin or balance_coin <= 0:
                return None

            current_price = self.api.get_current_price(ticker)
            avg_buy_price = self.api.get_buy_avg(ticker)

            if not current_price or not avg_buy_price:
                return None

            # 수익률 계산
            profit_rate = (current_price - avg_buy_price) / avg_buy_price * 100
            self.logger.info(f"현재 수익률: {profit_rate:.2f}% (현재가: {current_price:,}, 평균가: {avg_buy_price:,})")

            # 손절 금지 설정 확인
            prevent_loss_sale = self._get_field_value(getattr(self.args, 'prevent_loss_sale', None), 'Y')

            # 손절 라인 체크 (-3%) - prevent_loss_sale이 'Y'이면 손절하지 않음
            if profit_rate <= -3.0:
                if prevent_loss_sale == 'Y':
                    self.logger.info(f"손절 라인 도달하였으나 손절 금지 설정으로 매도하지 않음. 수익률: {profit_rate:.2f}%")
                    return None  # 손절하지 않음
                else:
                    self.logger.warning(f"손절 라인 도달! 수익률: {profit_rate:.2f}%")
                    return {'action': 'STOP_LOSS', 'reason': f'손절 라인 도달 ({profit_rate:.2f}%)', 'portion': 1.0}

            # 익절 라인 체크 (+5%)
            elif profit_rate >= 5.0:
                self.logger.info(f"익절 라인 도달! 수익률: {profit_rate:.2f}%")
                return {'action': 'TAKE_PROFIT', 'reason': f'익절 라인 도달 ({profit_rate:.2f}%)', 'portion': 0.5}

            # 트레일링 스톱 체크 (최고점 대비 -2%)
            trailing_result = self.check_trailing_stop(ticker, current_price, profit_rate)
            if trailing_result:
                return trailing_result

            return None

        except Exception as e:
            self.logger.error(f"손익 관리 체크 중 오류: {e}")
            return None

    def check_trailing_stop(self, ticker, current_price, current_profit_rate):
        """트레일링 스톱 체크"""
        try:
            # 최고점 추적을 위한 간단한 구현 (실제로는 더 정교한 구현 필요)
            if current_profit_rate > 3.0:  # 3% 이상 수익 시에만 트레일링 스톱 적용
                # 최근 15분간 최고가 대비 체크
                df = self.api.get_ohlcv_data(ticker, 'minute1', 15)
                if df is not None and len(df) > 0:
                    recent_high = df['high'].max()
                    if current_price < recent_high * 0.98:  # 최고점 대비 2% 하락
                        self.logger.info(f"트레일링 스톱 발동! 최고점: {recent_high:,}, 현재가: {current_price:,}")
                        return {'action': 'TRAILING_STOP', 'reason': '최고점 대비 2% 하락', 'portion': 0.7}

            return None
        except Exception as e:
            self.logger.error(f"트레일링 스톱 체크 중 오류: {e}")
            return None

    def get_ticker(self):
        """ticker 값을 안전하게 가져오기"""
        if isinstance(self.args, dict):
            return self.args.get('ticker', 'Unknown')
        elif hasattr(self.args, 'ticker'):
            return self._get_field_value(getattr(self.args, 'ticker', None), 'Unknown')
        else:
            return 'Unknown'

    def trading(self):
        """트레이딩 로직 실행"""
        try:
            # 기본 검증 먼저 수행
            if not self._validate_trading_conditions():
                return None

            # 스레드 모니터링 등록 (사용 가능한 경우만)
            if THREAD_MONITOR_AVAILABLE:
                ticker_value = self._get_field_value(self.args.get('ticker') if isinstance(self.args, dict) else getattr(self.args, 'ticker', None))
                strategy_value = self._get_field_value(self.args.get('strategy') if isinstance(self.args, dict) else getattr(self.args, 'strategy', None))

                thread_monitor.register_thread(
                    user_id=self.username,
                    ticker=ticker_value,
                    strategy=strategy_value
                )

            # 필드 값들을 안전하게 추출 - 통합된 방식
            ticker = self._get_field_value(
                self.args.get('ticker') if isinstance(self.args, dict) else getattr(self.args, 'ticker', None)
            )
            buy_amount = self._get_field_value(
                self.args.get('buy_amount') if isinstance(self.args, dict) else getattr(self.args, 'buy_amount', None)
            )
            min_cash = self._get_field_value(
                self.args.get('min_cash') if isinstance(self.args, dict) else getattr(self.args, 'min_cash', None)
            )
            # 매수 평단가 이하 매도 금지
            prevent_loss_sale = self._get_field_value(
                self.args.get('prevent_loss_sale') if isinstance(self.args, dict) else getattr(self.args, 'prevent_loss_sale', None),
                'Y'
            )
            # 장기 투자
            long_term_investment= self._get_field_value(
                self.args.get('long_term_investment') if isinstance(self.args, dict) else getattr(self.args, 'long_term_investment', None),
                'N'
            )
            # 최대 주문 금액 추가
            max_order_amount = self._get_field_value(
                self.args.get('max_order_amount') if isinstance(self.args, dict) else getattr(self.args, 'max_order_amount', None),
                0  # 기본값 5만원
            )

            # 전략 이름 안전하게 가져오기 - 개선된 부분
            strategy_name = self._get_field_value(
                self.args.get('strategy') if isinstance(self.args, dict) else getattr(self.args, 'strategy', None),
                'bollinger'  # 기본값을 'bollinger'로 변경
            )

            if not ticker:
                self.logger.error("티커 정보를 가져올 수 없습니다.")
                self.logger.error(f"디버그 - args 타입: {type(self.args)}")
                self.logger.error(f"디버그 - args 내용: {self.args}")
                return None

            if strategy_name == 'volatility':
                # 변동성 돌파 전략 사용
                self.logger.info(f"변동성 돌파 전략으로 거래 분석 시작: {ticker}")
                k_value = self._get_field_value(
                    self.args.get('k') if isinstance(self.args, dict) else getattr(self.args, 'k', None)
                )
                target_profit = self._get_field_value(
                    self.args.get('target_profit') if isinstance(self.args, dict) else getattr(self.args, 'target_profit', None)
                )
                stop_loss = self._get_field_value(
                    self.args.get('stop_loss') if isinstance(self.args, dict) else getattr(self.args, 'stop_loss', None)
                )
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
                rsi_period = self._get_field_value(
                    self.args.get('rsi_period') if isinstance(self.args, dict) else getattr(self.args, 'rsi_period', None)
                )
                rsi_oversold = self._get_field_value(
                    self.args.get('rsi_oversold') if isinstance(self.args, dict) else getattr(self.args, 'rsi_oversold', None)
                )
                rsi_overbought = self._get_field_value(
                    self.args.get('rsi_overbought') if isinstance(self.args, dict) else getattr(self.args, 'rsi_overbought', None)
                )
                rsi_timeframe = self._get_field_value(
                    self.args.get('rsi_timeframe') if isinstance(self.args, dict) else getattr(self.args, 'rsi_timeframe', None)
                )
                signal = self.strategy.generate_signal(ticker, rsi_period, rsi_oversold, rsi_overbought, rsi_timeframe)

            else:
                # 볼린저 밴드 전략 사용 (기본값)
                interval = self._get_field_value(
                    self.args.get('interval') if isinstance(self.args, dict) else getattr(self.args, 'interval', None)
                )
                window = self._get_field_value(
                    self.args.get('window') if isinstance(self.args, dict) else getattr(self.args, 'window', None)
                )
                multiplier = self._get_field_value(
                    self.args.get('multiplier') if isinstance(self.args, dict) else getattr(self.args, 'multiplier', None)
                )
                buy_multiplier = self._get_field_value(
                    self.args.get('buy_multiplier') if isinstance(self.args, dict) else getattr(self.args, 'buy_multiplier', None)
                )
                sell_multiplier = self._get_field_value(
                    self.args.get('sell_multiplier') if isinstance(self.args, dict) else getattr(self.args, 'sell_multiplier', None)
                )

                # 우선  use_rsi_filter, rsi_threshold 값을 default 로 셋팅하고 모니터링 해보자
                use_rsi_filter = True
                rsi_threshold = 30

                self.logger.info(f"볼린저 밴드 전략으로 거래 분석 시작: {ticker}, 간격: {interval}")
                self.logger.info(f"급락 방지 필터 사용: {use_rsi_filter}, RSI 임계값: {rsi_threshold}")

                # OHLCV 데이터 가져오기
                prices_data = self.api.get_ohlcv_data(ticker, interval, window + 5)  # 여유있게 가져옴

                if prices_data is None or len(prices_data) < window:
                    self.logger.error(f"가격 데이터를 충분히 가져오지 못했습니다. 받은 데이터 수: {0 if prices_data is None else len(prices_data)}")
                    return None

                # 종가 데이터만 추출
                prices = prices_data['close']

                if strategy_name == 'bollinger_asymmetric':
                    # 매매 신호 생성 (비대칭 볼린저 밴드 전략에 맞는 매개변수 전달)
                    signal_result = self.strategy.generate_signal(ticker, prices, window, buy_multiplier, sell_multiplier, use_rsi_filter, rsi_threshold, interval)
                else:
                    # 매매 신호 생성 (볼린저 밴드 전략에 맞는 매개변수 전달)
                    signal_result = self.strategy.generate_signal(ticker, prices, window, multiplier, use_rsi_filter, rsi_threshold, interval)

                signal = signal_result['signal']
                sell_ratio = signal_result.get('sell_ratio', 1.0)

                # 잔고 조회
                balance_cash = self.api.get_balance_cash()
                balance_coin = self.api.get_balance_coin(ticker)

                # 잔고 정보 로깅
                if balance_cash is not None:
                    self.logger.info(f"보유 현금: {balance_cash:,.2f}원")

                # 보유 코인 로깅 및 손익 관리
                if balance_coin is not None and balance_coin > 0:
                    avg_price = self.api.get_buy_avg(ticker)
                    current_price = self.api.get_current_price(ticker)

                    if avg_price and current_price:
                        profit_loss = (current_price - avg_price) / avg_price * 100
                        value = balance_coin * current_price
                        self.logger.info(f"보유 {ticker}: {balance_coin} (현재가: {current_price:,.2f} / 평균가: {avg_price:,.2f}, 현재가치: {value:,.2f}원, 수익률: {profit_loss:.2f}%)")

                    # 손익 관리 체크 (기존 전략보다 우선)
                    profit_loss_action = self.check_profit_loss_management(ticker, balance_coin)
                    if profit_loss_action:
                        self.logger.info(f"손익 관리 발동: {profit_loss_action['action']} - {profit_loss_action['reason']}")

                        # 손익 관리에 의한 매도 실행
                        sell_portion = profit_loss_action['portion']
                        if sell_portion >= 1.0:
                            # 전량 매도
                            order_result = self.api.order_sell_market(ticker, balance_coin)
                            self.logger.info(f"손익 관리에 의한 전량 매도 실행")
                        else:
                            # 부분 매도
                            order_result = self.api.order_sell_market_partial(ticker, sell_portion)
                            self.logger.info(f"손익 관리에 의한 부분 매도 실행 ({sell_portion*100:.1f}%)")

                        if order_result and 'error' not in order_result:
                            # 거래 기록 저장
                            current_price = self.api.get_current_price(ticker)
                            volume = balance_coin * sell_portion
                            amount = volume * current_price if current_price else 0
                            avg_buy_price = self.api.get_buy_avg(ticker)
                            profit_rate = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price else None

                            self.record_trade('SELL', ticker, current_price, volume, amount, profit_rate)

                            # 텔레그램 알림
                            self.send_trade_notification('SELL', ticker, {'volume': volume})

                        return order_result

                # 매매 신호에 따른 주문 처리
                if signal == 'BUY' and balance_cash and balance_cash > min_cash:
                    # 변동성 기반 포지션 사이징 적용
                    adjusted_buy_amount = self.calculate_volatility_based_position_size(ticker, buy_amount)
                    self.logger.info(f"변동성 기반 포지션 조정: {buy_amount:,}원 → {adjusted_buy_amount:,}원")
                    buy_amount = adjusted_buy_amount

                    # max_order_amount가 0이 아닌 경우에만 제한 로직 적용
                    if max_order_amount > 0:
                        # 현재 해당 코인의 보유량과 평균매수가 조회
                        current_balance = self.api.get_balance_coin(ticker) or 0
                        avg_buy_price = self.api.get_buy_avg(ticker) or 0

                        # 현재까지 투자한 총 금액 계산
                        total_invested_amount = current_balance * avg_buy_price if current_balance > 0 and avg_buy_price > 0 else 0

                        self.logger.info(f"({ticker}) - 현재 보유량: {current_balance}, 평균매수가: {avg_buy_price:,.2f}원")
                        self.logger.info(f"({ticker}) - 현재까지 투자한 총 금액: {total_invested_amount:,.2f}원")
                        self.logger.info(f"({ticker}) - 최대 주문 가능 금액: {max_order_amount:,.2f}원")

                        # 이미 투자한 금액이 최대 주문 금액을 초과하는 경우
                        if total_invested_amount >= max_order_amount:
                            self.logger.info(f"({ticker}) - 최대 주문 금액 초과로 매수를 건너뜁니다. (투자금액: {total_invested_amount:,.2f}원 >= 제한금액: {max_order_amount:,.2f}원)")
                            return None

                        # 남은 주문 가능 금액 계산
                        remaining_amount = max_order_amount - total_invested_amount

                        # 실제 매수 금액을 남은 금액과 비교하여 조정
                        actual_buy_amount = min(buy_amount, remaining_amount)

                        if actual_buy_amount != buy_amount:
                            self.logger.info(
                                f"매수 금액이 남은 주문 가능 금액으로 조정됨: {buy_amount:,.2f}원 → {actual_buy_amount:,.2f}원")

                        # 조정된 매수 금액이 최소 주문 금액보다 작은 경우
                        if actual_buy_amount < 5000:
                            self.logger.info(f"남은 주문 가능 금액이 최소 주문 금액(5,000원) 미만입니다. (남은 금액: {actual_buy_amount:,.2f}원)")
                            return None

                    else:
                        # max_order_amount가 0인 경우 제한 없이 매수
                        actual_buy_amount = buy_amount
                        self.logger.info("최대 주문 금액 제한 없음 (max_order_amount = 0)")

                    self.logger.info(f"매수 시그널 발생: {actual_buy_amount:,.2f}원 매수 시도")
                    order_result = self.api.order_buy_market(ticker, actual_buy_amount)

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
                            amount = actual_buy_amount  # 주문 금액 사용

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
                            estimated_volume = actual_buy_amount / current_price if current_price else 0
                            self.logger.info(f"예상 매수 수량: {estimated_volume} (현재가 기준)")

                            # 거래 기록 저장 (예상 수량 사용)
                            self.record_trade('BUY', ticker, current_price, estimated_volume, actual_buy_amount)

                    return order_result
                elif signal == 'SELL' or signal == 'PARTIAL_SELL' and balance_coin and balance_coin > 0:
                    self.logger.info(f"매도 시그널 발생: {balance_coin} {ticker.split('-')[1]} 매도 시도")

                    # 현재가 조회하여 보유 코인 가치 확인
                    current_price = self.api.get_current_price(ticker)
                    if not current_price:
                        self.logger.error("현재가를 조회할 수 없어 매도를 건너뜁니다.")
                        return None

                    if long_term_investment == 'Y':
                        self.logger.info(f"장기 보유 코인이므로 매도를 건너뜁니다.")
                        return None

                    avg_buy_price = self.api.get_buy_avg(ticker)  # 평단가를 미리 조회

                    # 손절 금지 설정을 확인하여 매도를 건너뜁니다. (기본값: Y) 최소 0.001는 먹자(0.1%는 수수료(매수/매도)를 주니까 -> 0.01%은 수수료, 0.01%은 먹자)
                    if prevent_loss_sale == 'Y' and avg_buy_price and current_price < (avg_buy_price * 1.002):
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
                    sell_portion = self._get_field_value(self.args.get('sell_portion') if isinstance(self.args, dict) else getattr(self.args, 'sell_portion', None),1.0)

                    # 매도 전략 결정
                    if sell_portion < 1.0:
                        # 현재 보유량과 가치 확인
                        balance = self.api.get_balance_coin(ticker)
                        current_price = self.api.get_current_price(ticker)

                        if balance and current_price:
                            total_value = balance * current_price
                            estimated_sell_value = total_value * sell_portion
                            min_order_value = 5000

                            # 최소 매도 금액 체크 및 조정
                            if estimated_sell_value < min_order_value:
                                if min_order_value <= total_value < 10000:
                                    # 전체 보유가 5,000원 이상 10,000원 미만인 경우 전량 매도
                                    self.logger.info(f"{ticker} 예상 매도 금액({estimated_sell_value:,.0f}원)이 최소 금액 미만으로 전량 매도로 변경")
                                    sell_portion = 1.0
                                    order_result = self.api.order_sell_market_partial(ticker, sell_portion)
                                elif total_value < min_order_value:
                                    # 전체 보유가 최소 금액 미만인 경우 매도 보류
                                    self.logger.warning(f"{ticker} 전체 보유가치({total_value:,.0f}원)가 최소 매도 금액 미만으로 매도 보류")
                                    order_result = {"error": {"name": "insufficient_value", "message": "최소 매도 금액 미만"}}
                                else:
                                    # 보유가치가 충분하지만 분할 매도 금액이 부족한 경우
                                    # 최소 금액을 충족하는 매도 비율로 조정
                                    adjusted_portion = min(1.0, (min_order_value + 1000) / total_value)  # 여유분 추가
                                    self.logger.info(f"{ticker} 매도 비율을 최소 금액 충족을 위해 {sell_portion:.2f}에서 {adjusted_portion:.2f}로 조정")
                                    sell_portion = adjusted_portion
                                    order_result = self.api.order_sell_market_partial(ticker, sell_portion)
                            else:
                                # 정상적인 분할 매도 진행
                                if signal == 'PARTIAL_SELL':
                                    sell_portion = sell_portion * sell_ratio
                                    self.logger.info(f"{ticker} 분할 매도 시도 및 RSI보조지표 사용(PARTIAL_SELL): 보유량의 {sell_portion * 100:.1f}% 매도, RSI보조지표: {sell_ratio}")
                                else:
                                    self.logger.info(f"{ticker} 분할 매도 시도: 보유량의 {sell_portion * 100:.1f}% 매도")
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
                            self.logger.error(f"{ticker} 보유량 또는 현재가 정보를 가져올 수 없음")
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
            ticker = self.get_ticker()  # 새로운 메서드 사용
            # ticker = self._get_field_value(getattr(self.args, 'ticker', None), 'Unknown')
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
            # 전역 앱 인스턴스 사용 (create_app 재호출 방지)
            try:
                from flask import current_app
                app = current_app._get_current_object()
            except RuntimeError:
                # 현재 앱 컨텍스트가 없는 경우 전역 앱 인스턴스 사용
                from app import app
                if not app:
                    self.logger.warning("앱 인스턴스를 찾을 수 없습니다. 거래 기록 저장을 건너뜁니다.")
                    return

            with app.app_context():
                from app.models import TradeRecord, db
                from app.models import kst_now

                # 매도인 경우 수익/손실률 계산
                if trade_type == 'SELL':
                    try:
                        avg_buy_price = self.api.get_buy_avg(ticker)
                        if avg_buy_price and avg_buy_price > 0:
                            profit_loss = ((price - avg_buy_price) / avg_buy_price) * 100
                            self.logger.info(f"수익률 계산: 매도가({price}) - 평균매수가({avg_buy_price}) = {profit_loss:.2f}%")
                    except Exception as e:
                        self.logger.warning(f"수익률 계산 실패: {str(e)}")

                # 전략 이름 안전하게 가져오기
                strategy_name = self._get_field_value(
                    self.args.get('strategy') if isinstance(self.args, dict) else getattr(self.args, 'strategy', None),
                    'bollinger'  # 기본값을 'bollinger'로 변경
                )

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
                    timestamp=kst_now()
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
            base_interval = self._get_field_value(getattr(self.args, 'sleep_time', None), 60)
            # 동적 거래 간격 적용
            ticker = self._get_field_value(getattr(self.args, 'ticker', None))
            if ticker:
                interval_seconds = self.calculate_dynamic_sleep_time(ticker, base_interval)
            else:
                interval_seconds = base_interval

        # interval_seconds를 정수로 변환
        try:
            interval_seconds = int(interval_seconds)
        except (ValueError, TypeError):
            interval_seconds = 60  # 기본값

        # 작업 ID 생성
        ticker = self._get_field_value(getattr(self.args, 'ticker', None))
        strategy = self._get_field_value(getattr(self.args, 'strategy', None))
        self.job_id = f"Trading_bot_{self.user_id}_{ticker}_{strategy}_{int(datetime.now().timestamp())}"

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

    def _validate_trading_conditions(self):
        """거래 실행 전 기본 조건 검증"""
        try:
            # API 키 유효성 검증
            is_valid, error_msg = self.api.validate_api_keys()
            if not is_valid:
                self.logger.error(f"API 키 검증 실패: {error_msg}")
                return False

            # 현금 잔고 조회 가능한지 확인
            cash_balance = self.api.get_balance_cash()
            if cash_balance is None:
                self.logger.error("현금 잔고 조회에 실패했습니다.")
                return False

            return True

        except Exception as e:
            self.logger.error(f"거래 조건 검증 중 오류: {e}")
            return False
