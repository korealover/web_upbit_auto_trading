# bot/trading_bot.py
from app.utils.telegram_utils import TelegramNotifier
from config import Config


class UpbitTradingBot:
    """업비트 자동 거래 봇 클래스"""

    def __init__(self, args, upbit_api, strategy, logger):
        """초기화"""
        self.args = args
        self.api = upbit_api
        self.strategy = strategy
        self.logger = logger

        # 텔레그램 알림 초기화
        self.telegram_enabled = Config.TELEGRAM_NOTIFICATIONS_ENABLED
        if self.telegram_enabled and Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
            self.telegram = TelegramNotifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID, logger)
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

            # 전략에 따라 분기
            if hasattr(self.args, 'strategy') and self.args.strategy.data == 'volatility':
                # 변동성 돌파 전략 사용
                self.logger.info(f"변동성 돌파 전략으로 거래 분석 시작: {ticker}")
                # 변동성 돌파 전략에 맞는 매개변수만 전달
                signal = self.strategy.generate_volatility_signal(ticker, self.args.k.data, self.args.target_profit.data, self.args.stop_loss.data)
            else:
                # 볼린저 밴드 전략 사용 (기본값)
                interval = self.args.interval.data
                window = self.args.window.data
                multiplier = self.args.multiplier.data
                print('value : ', interval, window, multiplier)

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
                    self.send_trade_notification('BUY', ticker, order_result)

                    # 거래 기록 저장
                    amount = float(order_result.get('price', 0))
                    volume = float(order_result.get('volume', 0))
                    price = self.api.get_current_price(ticker)
                    self.record_trade('BUY', ticker, price, volume, amount)

                return order_result

            elif signal == 'SELL' and balance_coin and balance_coin > 0:
                self.logger.info(f"매도 시그널 발생: {balance_coin} {ticker.split('-')[1]} 매도 시도")

                # 분할 매도 처리
                sell_portion = getattr(self.args, 'sell_portion', 1.0)  # 기본값 1.0 (전량 매도)

                # FloatField 객체에서 실제 값 가져오기
                if hasattr(sell_portion, 'data'):
                    sell_portion_value = sell_portion.data
                else:
                    sell_portion_value = sell_portion  # 이미 숫자인 경우

                if sell_portion_value < 1.0:
                    self.logger.info(f"분할 매도 시도: 보유량의 {sell_portion_value * 100:.1f}% 매도")
                    order_result = self.api.order_sell_market_partial(ticker, sell_portion_value)
                else:
                    self.logger.info(f"전량 매도 시도: {balance_coin} {ticker.split('-')[1]}")
                    order_result = self.api.order_sell_market(ticker, balance_coin)

                # 매도 완료 텔레그램 알림 전송
                if order_result and not isinstance(order_result, int) and 'error' not in order_result:
                    self.send_trade_notification('SELL', ticker, order_result)
                    # 거래 기록 저장 (수익률 포함)
                    volume = float(order_result.get('volume', 0))
                    price = self.api.get_current_price(ticker)
                    amount = price * volume
                    avg_buy_price = self.api.get_buy_avg(ticker)
                    profit_loss = ((price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price else None
                    self.record_trade('SELL', ticker, price, volume, amount, profit_loss)

                return order_result

            else:
                self.logger.info("포지션 유지 (매수/매도 조건 불충족)")

        except Exception as e:
            self.logger.error(f"거래 중 오류 발생: {str(e)}", exc_info=True)

        return None

    def run_cycle(self):
        """거래 사이클 실행"""
        try:
            self.logger.info(f"거래 사이클 시작: {self.args.ticker.data}")

            # 트레이딩 실행
            ret = self.trading()

            if ret:
                self.logger.info(f"거래 결과: {ret}")

            self.logger.info(f"거래 사이클 종료: {self.args.ticker.data}")

        except Exception as e:
            self.logger.error(f"실행 중 오류 발생: {str(e)}", exc_info=True)

    # trading_bot.py에 메서드 추가
    # trading_bot.py에 메서드 추가
    def record_trade(self, trade_type, ticker, price, volume, amount, profit_loss=None):
        """거래 기록 저장"""
        try:
            from app.models import TradeRecord, db

            # 사용자 ID 가져오기
            user_id = None
            if hasattr(self.args, 'user_id') and self.args.user_id:
                user_id = self.args.user_id

            # 전략 정보
            strategy = None
            if hasattr(self.args, 'strategy') and hasattr(self.args.strategy, 'data'):
                strategy = self.args.strategy.data
            elif isinstance(self.args, dict) and 'strategy' in self.args:
                strategy = self.args['strategy']
            else:
                strategy = 'bollinger'

            # 새 거래 기록 생성
            trade_record = TradeRecord(
                user_id=user_id,
                ticker=ticker,
                trade_type=trade_type,
                price=price,
                volume=volume,
                amount=amount,
                profit_loss=profit_loss,
                strategy=strategy
            )

            # 데이터베이스에 저장
            db.session.add(trade_record)
            db.session.commit()

            self.logger.info(f"거래 기록 저장 완료: {trade_type} {ticker} {volume} @ {price}")
        except Exception as e:
            self.logger.error(f"거래 기록 저장 중 오류: {str(e)}")