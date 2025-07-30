from app.strategy.volume_base_buy import VolumeBasedBuyStrategy


class BollingerBandsStrategy:
    """볼린저 밴드 기반 트레이딩 전략"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger
        self.volume_analyzer = VolumeBasedBuyStrategy(upbit_api, logger)

    def get_bollinger_bands(self, prices, window=20, multiplier=2):
        """볼린저 밴드 계산"""
        self.logger.info(f"볼린저 밴드 계산 시작 (window={window}, multiplier={multiplier})")

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

        self.logger.info(f"볼린저 밴드 계산 완료")

        return upper_band, lower_band

    def should_delay_buy(self, ticker):
        """매수를 지연해야 하는지 판단"""
        try:
            volume_data = self.volume_analyzer.analyze_sell_pressure(ticker)
            if not volume_data:
                self.logger.info(f"매도 압력 데이터가 없어 매수 지연 검사를 건너뜁니다: {ticker}")
                return False

            self.logger.info(f"매도 압력 데이터({ticker}): {volume_data}")

            # 매도 압력이 높은 경우 매수 지연
            if volume_data['sell_buy_ratio'] > 2.0:  # 매도 물량이 매수 물량의 2배 이상
                self.logger.info(f"높은 매도 압력으로 매수 지연 (매도/매수 비율: {volume_data['sell_buy_ratio']:.2f})")
                return True

            # 거래량이 평소보다 크게 증가한 경우 (매도 물량 급증 가능성)
            if volume_data['volume_ratio'] > 3.0:
                self.logger.info(f"거래량 급증으로 매수 지연 (거래량 비율: {volume_data['volume_ratio']:.2f})")
                return True

            # 추가 시장 심리 분석
            sentiment = self.volume_analyzer.get_market_sentiment(ticker)
            self.logger.info(f"시장 심리 분석 결과({ticker}): {sentiment}")
            if sentiment and sentiment['spread_ratio'] > 0.01:  # 스프레드가 1% 이상
                self.logger.info(f"높은 스프레드로 매수 지연 (스프레드 비율: {sentiment['spread_ratio'] * 100:.2f}%)")
                return True

            return False

        except Exception as e:
            self.logger.error(f"매수 지연 판단 중 오류: {e}")
            return False

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

        self.logger.info(f"매도밴드: {band_high:.2f} / 매수밴드: {band_low:.2f} / {ticker} PRICE: {cur_price:.2f}")

        if cur_price > band_high:
            self.logger.info(f"매도 신호 발생 (현재가 > 상단밴드: {cur_price:.2f} > {band_high:.2f})")
            return 'SELL'
        elif cur_price < band_low:
            # 매수 신호 발생 시 매도 물량 확인
            if self.should_delay_buy(ticker):
                self.logger.info(f"매수 조건 충족하지만 매도 압력으로 인해 대기")
                return 'HOLD'
            else:
                self.logger.info(f"매수 신호 발생 (현재가 < 하단밴드: {cur_price:.2f} < {band_low:.2f})")
                return 'BUY'
        else:
            self.logger.info("홀드 신호 (현재가가 밴드 내에 있음)")
            return 'HOLD'