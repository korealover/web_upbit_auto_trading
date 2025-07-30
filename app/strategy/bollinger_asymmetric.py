from app.strategy.volume_base_buy import VolumeBasedBuyStrategy


class AsymmetricBollingerBandsStrategy:
    """비대칭 볼린저 밴드 전략 - 매수와 매도에 다른 승수 사용"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger
        self.volume_analyzer = VolumeBasedBuyStrategy(upbit_api, logger)


    def get_bollinger_bands(self, prices, window=20, buy_multiplier=3.0, sell_multiplier=2.0):
        """비대칭 볼린저 밴드 계산"""
        self.logger.info(f"비대칭 볼린저 밴드 계산 시작 (window={window}, buy_multiplier={buy_multiplier}, sell_multiplier={sell_multiplier})")

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

        self.logger.info(f"비대칭 볼린저 밴드 계산 완료")

        return sell_upper_band, buy_lower_band

    def should_delay_buy(self, ticker):
        """매수를 지연해야 하는지 판단"""
        try:
            volume_data = self.volume_analyzer.analyze_sell_pressure(ticker)
            if not volume_data:
                self.logger.info(f"매도 압력 데이터가 없어 매수 지연 검사를 건너뜁니다: {ticker}")
                return False

            self.logger.info(f"매도 압력 데이터({ticker}): {volume_data}")

            # 매도 압력이 높은 경우 매수 지연
            if volume_data['sell_buy_ratio'] > 2.5:  # 비대칭 전략이므로 더 보수적으로 설정
                self.logger.info(f"높은 매도 압력으로 매수 지연 (매도/매수 비율: {volume_data['sell_buy_ratio']:.2f})")
                return True

            # 거래량이 평소보다 크게 증가한 경우
            if volume_data['volume_ratio'] > 2.5:
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
            # 매수 신호 발생 시 매도 물량 확인
            if self.should_delay_buy(ticker):
                self.logger.info(f"매수 조건 충족하지만 매도 압력으로 인해 대기")
                return 'HOLD'
            else:
                self.logger.info(f"매수 신호 발생 (현재가 < 매수밴드(3.0σ): {cur_price:.2f} < {buy_band_low:.2f})")
                return 'BUY'
        else:
            self.logger.info("홀드 신호 (현재가가 매매 조건에 해당하지 않음)")
            return 'HOLD'