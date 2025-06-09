import datetime


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

    def is_trading_time(self):
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

        # 매도 시간 확인 (오전 8:50 ~ 10:00 사이)
        sell_start = now.replace(hour=8, minute=50, second=0, microsecond=0)
        sell_end = now.replace(hour=10, minute=0, second=0, microsecond=0)

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
        if not self.is_trading_time():
            self.logger.info("현재는 거래 시간이 아닙니다.")
            return 'HOLD'

        # ===== 매수 신호 개선 부분 시작 =====

        # 1. 일일 OHLCV 데이터 가져오기 (최근 5일)
        df_daily = self.api.get_ohlcv_data(ticker, 'day', 5)
        if df_daily is None or len(df_daily) < 3:
            self.logger.warning("OHLCV 데이터를 충분히 가져오지 못했습니다. 기본 로직으로 진행합니다.")
        else:
            # 2. 추가 지표 계산
            # 2-1. 거래량 증가 확인 (전일 대비)
            today_volume = df_daily.iloc[-1]['volume']
            yesterday_volume = df_daily.iloc[-2]['volume']
            volume_increase = today_volume > yesterday_volume * 1.2  # 20% 이상 증가

            # 2-2. 전일 양봉 확인
            yesterday_open = df_daily.iloc[-2]['open']
            yesterday_close = df_daily.iloc[-2]['close']
            yesterday_bullish = yesterday_close > yesterday_open

            # 2-3. 오늘 시가 상승 확인
            today_open = df_daily.iloc[-1]['open']
            today_open_increase = today_open > yesterday_close * 1.01  # 1% 이상 상승 시작

            # 3. 시간대별 매수 조건 조정
            morning_buying = now.hour >= 10 and now.hour < 12  # 오전 10시 ~ 12시
            afternoon_buying = now.hour >= 13 and now.hour < 15  # 오후 1시 ~ 3시

            # 4. 매수 신호 조건 강화
            basic_condition = current_price > target_price and (not balance_coin or balance_coin == 0)

            # 아침 시간대는 기본 조건만으로 매수 (변동성 돌파 전략의 기본 원칙)
            if morning_buying and basic_condition:
                self.logger.info(f"오전 매수 신호 발생 (현재가 > 목표가: {current_price:.2f} > {target_price:.2f})")
                return 'BUY'

            # 오후 시간대는 추가 조건 확인
            if afternoon_buying and basic_condition:
                # 거래량 증가 또는 전일 양봉일 때만 매수
                if volume_increase or yesterday_bullish:
                    self.logger.info(f"오후 매수 신호 발생 - 거래량 증가: {volume_increase}, 전일 양봉: {yesterday_bullish}")
                    return 'BUY'
                else:
                    self.logger.info("오후 시간대 추가 조건 불충족으로 매수 보류")

            # 목표가 초과 폭이 큰 경우 (상승 추세가 강한 경우)
            price_ratio = current_price / target_price
            if basic_condition and price_ratio > 1.02:  # 목표가보다 2% 이상 높을 때
                self.logger.info(f"강한 상승세 감지 - 목표가 대비 {(price_ratio - 1) * 100:.2f}% 높음")
                return 'BUY'

        # ===== 매수 신호 개선 부분 끝 =====

        self.logger.info(f"변동성 돌파 전략 - 목표가: {target_price:.2f} / 현재가: {current_price:.2f}")

        # 기존 기본 매수 조건 (보유 코인이 없고 현재가 > 목표가)
        if current_price > target_price and (not balance_coin or balance_coin == 0):
            self.logger.info(f"기본 매수 신호 발생 (현재가 > 목표가: {current_price:.2f} > {target_price:.2f})")
            return 'BUY'
        else:
            self.logger.info(f"홀드 신호 (현재가 <= 목표가 또는 코인 보유 중)")
            return 'HOLD'