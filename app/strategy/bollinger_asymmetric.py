class AsymmetricBollingerBandsStrategy:
    """비대칭 볼린저 밴드 전략 - 매수와 매도에 다른 승수 사용"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

    def get_bollinger_bands(self, prices, window=20, buy_multiplier=3.0, sell_multiplier=2.0):
        """비대칭 볼린저 밴드 계산"""
        self.logger.debug(f"비대칭 볼린저 밴드 계산 시작 (window={window}, buy_multiplier={buy_multiplier}, sell_multiplier={sell_multiplier})")

        # 입력 파라미터 검증 및 타입 변환
        try:
            window = int(window)
            buy_multiplier = float(buy_multiplier)
            sell_multiplier = float(sell_multiplier)
        except (ValueError, TypeError) as e:
            self.logger.error(f"파라미터 타입 변환 오류: window={window}, buy_multiplier={buy_multiplier}, sell_multiplier={sell_multiplier}, 오류: {e}")
            raise ValueError(f"Invalid parameter types: window must be int, multipliers must be float")

        # 이동평균 및 표준편차 계산
        sma = prices.rolling(window).mean()
        rolling_std = prices.rolling(window).std()

        # 매수용 하단밴드 (승수 3.0)
        buy_lower_band = sma - (rolling_std * buy_multiplier)

        # 매도용 상단밴드 (승수 2.0)
        sell_upper_band = sma + (rolling_std * sell_multiplier)

        self.logger.debug(f"비대칭 볼린저 밴드 계산 완료")

        return sell_upper_band, buy_lower_band

    def generate_signal(self, ticker, prices, window, buy_multiplier=3.0, sell_multiplier=2.0):
        """매매 신호 생성"""
        sell_upper_band, buy_lower_band = self.get_bollinger_bands(
            prices, window, buy_multiplier, sell_multiplier
        )

        # 마지막 값만 필요하므로 최적화
        sell_band_high = sell_upper_band.iloc[-1]
        buy_band_low = buy_lower_band.iloc[-1]
        cur_price = self.api.get_current_price(ticker)

        if cur_price is None:
            self.logger.error("현재가를 가져올 수 없어 신호 생성을 중단합니다.")
            return 'HOLD'

        self.logger.info(f"매도밴드(2.0σ): {sell_band_high:.2f} / 매수밴드(3.0σ): {buy_band_low:.2f} / {ticker} PRICE: {cur_price:.2f}")

        if cur_price > sell_band_high:
            self.logger.info(f"매도 신호 발생 (현재가 > 매도밴드(2.0σ): {cur_price:.2f} > {sell_band_high:.2f})")
            return 'SELL'
        elif cur_price < buy_band_low:
            self.logger.info(f"매수 신호 발생 (현재가 < 매수밴드(3.0σ): {cur_price:.2f} < {buy_band_low:.2f})")
            return 'BUY'
        else:
            self.logger.info("홀드 신호 (현재가가 매매 조건에 해당하지 않음)")
            return 'HOLD'