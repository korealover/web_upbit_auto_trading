class BollingerBandsStrategy:
    """볼린저 밴드 기반 트레이딩 전략"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

    def get_bollinger_bands(self, prices, window=20, multiplier=2):
        """볼린저 밴드 계산"""
        self.logger.debug(f"볼린저 밴드 계산 시작 (window={window}, multiplier={multiplier})")

        # 입력 파라미터 검증 및 타입 변환
        try:
            window = int(window)
            multiplier = float(multiplier)
        except (ValueError, TypeError) as e:
            self.logger.error(f"파라미터 타입 변환 오류: window={window}, multiplier={multiplier}, 오류: {e}")
            raise ValueError(f"Invalid parameter types: window must be int, multiplier must be float")

        # 이동평균 및 표준편차 계산
        sma = prices.rolling(window).mean()
        rolling_std = prices.rolling(window).std()

        upper_band = sma + (rolling_std * multiplier)
        lower_band = sma - (rolling_std * multiplier)

        self.logger.debug(f"볼린저 밴드 계산 완료")

        return upper_band, lower_band

    def generate_signal(self, ticker, prices, window, multiplier):
        """매매 신호 생성"""
        upper_band, lower_band = self.get_bollinger_bands(prices, window, multiplier)

        # 마지막 값만 필요하므로 최적화
        band_high = upper_band.iloc[-1]
        band_low = lower_band.iloc[-1]
        cur_price = self.api.get_current_price(ticker)

        if cur_price is None:
            self.logger.error("현재가를 가져올 수 없어 신호 생성을 중단합니다.")
            return 'HOLD'

        self.logger.info(f"HIGH: {band_high:.2f} / LOW: {band_low:.2f} / {ticker} PRICE: {cur_price:.2f}")

        if cur_price > band_high:
            self.logger.info(f"매도 신호 발생 (현재가 > 상단밴드: {cur_price:.2f} > {band_high:.2f})")
            return 'SELL'
        elif cur_price < band_low:
            self.logger.info(f"매수 신호 발생 (현재가 < 하단밴드: {cur_price:.2f} < {band_low:.2f})")
            return 'BUY'
        else:
            self.logger.info("홀드 신호 (현재가가 밴드 내에 있음)")
            return 'HOLD'