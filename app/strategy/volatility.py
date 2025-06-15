import datetime


def is_trading_time():
    """거래 시간 확인 (9시부터 다음날 8시 50분까지)"""
    now = datetime.datetime.now()
    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=8, minute=50, second=0, microsecond=0)

    # 당일 9시부터 다음날 8시 50분까지 거래 가능
    if now.hour < 9:
        # 당일 0시 ~ 9시 전
        yesterday = now - datetime.timedelta(days=1)
        market_start = yesterday.replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        # 당일 9시 이후
        tomorrow = now + datetime.timedelta(days=1)
        market_end = tomorrow.replace(hour=8, minute=50, second=0, microsecond=0)

    return market_start <= now <= market_end


class VolatilityBreakoutStrategy:
    """변동성 돌파 전략 클래스"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

    def calculate_target_price(self, ticker, k):
        """변동성 돌파 전략의 매수 목표가 계산"""
        try:
            # 일봉 데이터 가져오기
            df = self.api.get_ohlcv_data(ticker, 'day', 2)
            if df is None or len(df) < 2:
                self.logger.error("목표가 계산을 위한 OHLCV 데이터를 가져오지 못했습니다.")
                return None

            # 전일 데이터
            yesterday = df.iloc[-2]
            today_open = df.iloc[-1]['open']

            # 변동폭 계산 (전일 고가 - 전일 저가)
            volatility = yesterday['high'] - yesterday['low']

            # 매수 목표가 = 당일 시가 + (전일 변동폭 * k)
            target_price = today_open + (volatility * k)

            self.logger.info(f"변동성 돌파 목표가 계산: 시가({today_open:,.2f}) + 변동폭({volatility:,.2f}) * k({k}) = {target_price:,.2f}")
            return target_price

        except Exception as e:
            self.logger.error(f"목표가 계산 중 오류: {str(e)}")
            return None

    def generate_volatility_signal(self, ticker, k=0.5, target_profit=3.0, stop_loss=-2.0):
        """변동성 돌파 전략 매매 신호 생성

        Args:
            ticker (str): 티커 심볼
            k (float): 변동성 계수 (기본값 0.5)
            target_profit (float): 목표 수익률 (%)
            stop_loss (float): 손절 손실률 (%)

        Returns:
            str: 'BUY', 'SELL', 'HOLD' 중 하나의 신호
        """
        now = datetime.datetime.now()

        # 매도 시간 확인 (오전 8:50 ~ 9:00 사이)
        sell_start = now.replace(hour=8, minute=50, second=0, microsecond=0)
        sell_end = now.replace(hour=9, minute=0, second=0, microsecond=0)

        # 현재 코인 보유량 확인
        balance_coin = self.api.get_balance_coin(ticker)

        # 코인을 보유하고 있다면 매도 조건 확인
        if balance_coin and balance_coin > 0:
            # 1. 시간 기준 매도
            if sell_start <= now < sell_end:
                self.logger.info(f"매도 시간에 도달했습니다. 매도 신호 발생")
                return 'SELL'

            # 2. 수익률 기준 매도
            avg_price = self.api.get_buy_avg(ticker)
            current_price = self.api.get_current_price(ticker)

            if avg_price and current_price:
                profit_loss = (current_price - avg_price) / avg_price * 100

                # 목표 수익률 도달 시 매도
                if profit_loss >= target_profit:
                    self.logger.info(f"목표 수익률({target_profit}%)에 도달했습니다. 현재 수익률: {profit_loss:.2f}%. 매도 신호 발생")
                    return 'SELL'

                # 손절 손실률 도달 시 매도
                if profit_loss <= stop_loss:
                    self.logger.info(f"손절 손실률({stop_loss}%)에 도달했습니다. 현재 수익률: {profit_loss:.2f}%. 매도 신호 발생")
                    return 'SELL'

        # 목표가 계산
        target_price = self.calculate_target_price(ticker, k)
        if target_price is None:
            return 'HOLD'

        # 현재가 조회
        current_price = self.api.get_current_price(ticker)
        if current_price is None:
            self.logger.error("현재가를 가져올 수 없어 신호 생성을 중단합니다.")
            return 'HOLD'

        # 거래 시간 확인
        if not is_trading_time():
            self.logger.info("현재는 거래 시간이 아닙니다.")
            return 'HOLD'

        self.logger.info(f"변동성 돌파 전략 - 목표가: {target_price:.2f} / 현재가: {current_price:.2f}")

        # 매수 신호: 현재가 > 목표가 (코인을 보유하고 있지 않을 때만)
        if current_price > target_price and (not balance_coin or balance_coin == 0):
            self.logger.info(f"매수 신호 발생 (현재가 > 목표가: {current_price:.2f} > {target_price:.2f})")
            return 'BUY'
        else:
            self.logger.info(f"홀드 신호 (현재가 <= 목표가 또는 코인 보유 중)")
            return 'HOLD'