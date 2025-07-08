# bot/trading_bot.py
from flask_login import current_user

from app.utils.telegram_utils import TelegramNotifier
from config import Config
from app.models import TradeRecord
from app import db
import datetime
import time


class UpbitTradingBot:
    """업비트 자동 거래 봇 클래스"""

    def __init__(self, args, upbit_api, strategy, logger, username=None):
        """초기화"""
        self.args = args
        self.api = upbit_api
        self.strategy = strategy
        self.logger = logger
        self.username = username

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

    def trading(self):
        """트레이딩 로직 실행"""
        try:
            ticker = self.args.ticker.data
            buy_amount = self.args.buy_amount.data
            min_cash = self.args.min_cash.data
            prevent_loss_sale = self.args.prevent_loss_sale.data

            # 전략에 따라 분기
            if hasattr(self.args, 'strategy') and self.args.strategy.data == 'volatility':
                # 변동성 돌파 전략 사용
                self.logger.info(f"변동성 돌파 전략으로 거래 분석 시작: {ticker}")
                # 변동성 돌파 전략에 맞는 매개변수만 전달
                signal = self.strategy.generate_volatility_signal(ticker, self.args.k.data, self.args.target_profit.data, self.args.stop_loss.data)
            elif hasattr(self.args, 'strategy') and self.args.strategy.data == 'adaptive':
                # 어댑티브 전략 사용
                self.logger.info(f"어댑티브 전략으로 거래 분석 시작: {ticker}")
                # 어댑티브 전략은 ticker만 필요
                signal = self.strategy.generate_signal(ticker)
            elif hasattr(self.args, 'strategy') and self.args.strategy.data == 'ensemble':
                # 앙상블 전략 사용
                self.logger.info(f"앙상블 전략으로 거래 분석 시작: {ticker}")
                # 앙상블 전략은 ticker만 필요
                signal = self.strategy.generate_signal(ticker)
            elif hasattr(self.args, 'strategy') and self.args.strategy.data == 'rsi':
                # RSI 전략 사용
                self.logger.info(f"RSI 전략으로 거래 분석 시작: {ticker}")
                # RSI 전략은 ticker만 필요
                signal = self.strategy.generate_signal(ticker, self.args.rsi_period.data, self.args.rsi_oversold.data, self.args.rsi_overbought.data, self.args.rsi_timeframe.data)
            else:
                # 볼린저 밴드 전략 사용 (기본값)
                interval = self.args.interval.data
                window = self.args.window.data
                multiplier = self.args.multiplier.data

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
                # signal = 'BUY'

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
                sell_portion = getattr(self.args, 'sell_portion', 1.0)  # 기본값 1.0 (전량 매도)

                # FloatField 객체에서 실제 값 가져오기
                if hasattr(sell_portion, 'data'):
                    sell_portion_value = sell_portion.data
                else:
                    sell_portion_value = sell_portion  # 이미 숫자인 경우

                # 매도 전략 결정
                if sell_portion_value < 1.0:
                    self.logger.info(f"분할 매도 시도: 보유량의 {sell_portion_value * 100:.1f}% 매도")
                    order_result = self.api.order_sell_market_partial(ticker, sell_portion_value)

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
                        self.logger.info(f"실제 매도된 비율: {actual_portion * 100:.1f}% (원래 계획: {sell_portion_value * 100:.1f}%)")
                    elif sell_portion_value < 1.0:
                        volume = balance_coin * sell_portion_value
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
            self.logger.info("="*20 + f" 거래자 ID : {self.username} " + "="*20)
            self.logger.info(f"거래 사이클 시작: {self.args.ticker.data}")

            # 트레이딩 실행
            ret = self.trading()

            if ret:
                self.logger.info(f"거래 결과: {ret}")

            self.logger.info(f"거래 사이클 종료: {self.args.ticker.data}")
            self.logger.info("="*60)

        except Exception as e:
            self.logger.error(f"실행 중 오류 발생: {str(e)}", exc_info=True)

    def record_trade(self, trade_type, ticker, price, volume, amount, profit_loss=None):
        """거래 기록 저장"""
        try:
            # Flask 애플리케이션 컨텍스트를 정확하게 가져오기
            from app import create_app
            from config import Config

            # 현재 앱 인스턴스 가져오기 또는 새로 생성
            try:
                from flask import current_app
                app = current_app._get_current_object()
            except RuntimeError:
                # 현재 앱 컨텍스트가 없는 경우 새로 생성
                app = create_app(Config)

            with app.app_context():
                from app.models import TradeRecord, db
                from app.models import kst_now  # 한국 시간 함수 import

                # 매도인 경우 수익/손실률 계산
                # profit_loss = None
                if trade_type == 'SELL':
                    try:
                        # 평균 매수가 가져오기
                        avg_buy_price = self.api.get_buy_avg(ticker)
                        if avg_buy_price and avg_buy_price > 0:
                            profit_loss = ((price - avg_buy_price) / avg_buy_price) * 100
                            self.logger.info(f"수익률 계산: 매도가({price}) - 평균매수가({avg_buy_price}) = {profit_loss:.2f}%")
                    except Exception as e:
                        self.logger.warning(f"수익률 계산 실패: {str(e)}")

                # TradeRecord 생성 및 저장
                trade_record = TradeRecord(
                    user_id=self.user_id,
                    ticker=ticker,
                    trade_type=trade_type,
                    price=price,
                    volume=volume,
                    amount=amount,
                    profit_loss=profit_loss,
                    strategy=self.args.strategy.data if hasattr(self.args, 'strategy') else 'unknown',
                    timestamp=kst_now()  # UTC 대신 한국 시간 사용
                )

                db.session.add(trade_record)
                db.session.commit()

                self.logger.info(f"거래 기록 저장 완료: {trade_type} {ticker} {volume} @ {price}")

        except Exception as e:
            self.logger.error(f"거래 기록 저장 중 오류: {str(e)}")
            import traceback
            self.logger.error(f"상세 오류: {traceback.format_exc()}")
