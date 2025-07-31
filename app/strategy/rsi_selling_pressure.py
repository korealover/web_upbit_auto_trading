from app.strategy.rsi import RSIStrategy
from app.strategy.volume_base_buy import VolumeBasedBuyStrategy


class RSIVolumeIntegratedStrategy:
    """RSI와 매도 압력을 통합한 매수 조정 전략"""

    def __init__(self, upbit_api, logger):
        self.api = upbit_api
        self.logger = logger
        self.rsi_strategy = RSIStrategy(upbit_api, logger)
        self.volume_analyzer = VolumeBasedBuyStrategy(upbit_api, logger)

    def is_rsi_oversold(self, ticker, rsi_threshold=30, rsi_period=14):
        """RSI 과매도 상태 확인"""
        try:
            # RSI 계산을 위한 데이터 조회
            df = self.api.get_ohlcv_data(ticker, 'minute5', 50)
            if df is None or len(df) < rsi_period + 5:
                self.logger.warning(f"RSI 계산용 데이터 부족: {ticker}")
                return False, 50

            # RSI 계산
            rsi_values = self.rsi_strategy.calculate_rsi(df['close'], rsi_period)
            current_rsi = rsi_values.iloc[-1]

            self.logger.info(f"현재 RSI: {current_rsi:.2f}, 과매도 기준: {rsi_threshold}")

            # RSI가 과매도 구간에 있는지 확인
            is_oversold = current_rsi <= rsi_threshold
            return is_oversold, current_rsi

        except Exception as e:
            self.logger.error(f"RSI 과매도 확인 실패: {e}")
            return False, 50

    def should_delay_buy_with_rsi_filter(self, ticker, rsi_threshold=30):
        """RSI 과매도 구간에서만 매도 압력을 고려한 매수 지연 판단"""
        try:
            # 1단계: RSI 과매도 상태 확인
            is_oversold, current_rsi = self.is_rsi_oversold(ticker, rsi_threshold)

            if not is_oversold:
                # RSI가 과매도가 아니면 매도 압력 분석 건너뛰기
                self.logger.info(f"RSI({current_rsi:.2f}) 과매도 상태 아님 - 매도 압력 분석 건너뛰고 매수 진행")
                return False

            # 2단계: RSI 과매도 상태에서만 매도 압력 분석
            self.logger.info(f"RSI({current_rsi:.2f}) 과매도 상태 - 매도 압력 분석 진행")
            volume_data = self.volume_analyzer.analyze_sell_pressure(ticker)

            if not volume_data:
                self.logger.info("매도 압력 데이터 없음 - 매수 진행")
                return False

            # 3단계: 과매도 상태에서의 매도 압력 기준 (더 엄격하게)
            if volume_data['sell_buy_ratio'] > 3.0:
                self.logger.info(f"과매도 + 높은 매도 압력으로 매수 지연 (매도/매수 비율: {volume_data['sell_buy_ratio']:.2f})")
                return True

            if volume_data['volume_ratio'] > 4.0:
                self.logger.info(f"과매도 + 거래량 급증으로 매수 지연 (거래량 비율: {volume_data['volume_ratio']:.2f})")
                return True

            # 4단계: 추가 시장 심리 분석
            sentiment = self.volume_analyzer.get_market_sentiment(ticker)
            if sentiment and sentiment['spread_ratio'] > 0.02:  # 과매도에서는 2% 이상
                self.logger.info(f"과매도 + 높은 스프레드로 매수 지연 (스프레드 비율: {sentiment['spread_ratio'] * 100:.2f}%)")
                return True

            self.logger.info(f"과매도 상태지만 매도 압력 양호 - 매수 진행")
            return False

        except Exception as e:
            self.logger.error(f"RSI 기반 매수 지연 판단 실패: {e}")
            return False