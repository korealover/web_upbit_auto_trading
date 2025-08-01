from app.strategy.rsi import RSIStrategy
from app.strategy.volume_base_buy import VolumeBasedBuyStrategy
import pandas as pd

COIN_CATEGORIES = {
    'major': ['KRW-BTC', 'KRW-ETH'],
    'high_volatility': ['KRW-DOGE', 'KRW-SHIB', 'KRW-PEPE', 'KRW-WIF', 'KRW-BONK'],
    'stable': ['KRW-USDT', 'KRW-USDC'],
    'mid_tier': ['KRW-ADA', 'KRW-DOT', 'KRW-LINK', 'KRW-MATIC', 'KRW-SOL']
}


def _get_volatility_multiplier(volatility_level):
    """변동성에 따른 기준 조정 배수"""
    multipliers = {
        'VERY_HIGH': 1.5,  # 고변동성일 때 기준 완화
        'HIGH': 1.2,
        'MEDIUM': 1.0,  # 기본값
        'LOW': 0.8  # 저변동성일 때 기준 강화
    }
    return multipliers.get(volatility_level, 1.0)


def get_coin_specific_thresholds(ticker, base_thresholds):
    """코인별 특성을 고려한 기준 조정"""

    # 코인 분류별 multiplier
    multipliers = {
        'major': 0.8,  # 안정적
        'high_volatility': 1.3,  # 고변동성
        'stable': 0.6,  # 매우 안정적
        'mid_tier': 1.1  # 중간 변동성
    }

    # 해당 코인의 카테고리 찾기
    coin_multiplier = 1.0  # 기본값
    for category, coins in COIN_CATEGORIES.items():
        if ticker in coins:
            coin_multiplier = multipliers[category]
            break

    # 기준값 조정
    adjusted_thresholds = {}
    for period, threshold in base_thresholds.items():
        adjusted_thresholds[period] = threshold * coin_multiplier

    return adjusted_thresholds


class RSIVolumeIntegratedStrategy:
    """급락 감지 및 점진적 매수 전략"""

    def __init__(self, upbit_api, logger):
        self.api = upbit_api
        self.logger = logger
        self.rsi_strategy = RSIStrategy(upbit_api, logger)
        self.volume_analyzer = VolumeBasedBuyStrategy(upbit_api, logger)

    def detect_rapid_decline(self, ticker, lookback_periods=5):
        """급격한 가격 하락 감지 (기존 15분봉 기반)"""
        try:
            # 최근 데이터 조회 (15분봉 기준으로 복원)
            df = self.api.get_ohlcv_data(ticker, 'minute15', lookback_periods + 10)
            if df is None or len(df) < lookback_periods + 5:
                self.logger.warning(f"급락 감지용 데이터 부족: {ticker}")
                return False, 0, {}

            # 일관성을 위해 close 가격 사용
            prices = df['close']
            current_price = prices.iloc[-1]

            # 다양한 기간별 하락률 계산
            decline_analysis = {}

            # 1. 최근 15분봉 하락률
            if len(prices) >= 2:
                recent_decline = (current_price - prices.iloc[-2]) / prices.iloc[-2] * 100
                decline_analysis['1_period'] = recent_decline

            # 2. 최근 3개 봉 하락률
            if len(prices) >= 4:
                three_period_decline = (current_price - prices.iloc[-4]) / prices.iloc[-4] * 100
                decline_analysis['3_period'] = three_period_decline

            # 3. 최근 5개 봉 하락률
            if len(prices) >= 6:
                five_period_decline = (current_price - prices.iloc[-6]) / prices.iloc[-6] * 100
                decline_analysis['5_period'] = five_period_decline

            # 급락 기준 설정 (기존 보수적 기준에서 완화)
            rapid_decline_thresholds = {
                '1_period': -2.5,  # 15분에서 2.5% 하락 (기존 3%에서 완화)
                '3_period': -4.0,  # 45분에서 4% 하락 (기존 8%에서 대폭 완화)
                '5_period': -6.0  # 1시간 15분에서 6% 하락 (기존 15%에서 대폭 완화)
            }

            # 급락 감지
            is_rapid_decline = False
            decline_severity = 0

            for period, decline_rate in decline_analysis.items():
                threshold = rapid_decline_thresholds.get(period, 0)
                if decline_rate <= threshold:
                    is_rapid_decline = True
                    # 급락 심각도 계산 (기준 대비 얼마나 더 떨어졌는지)
                    severity = abs(decline_rate) / abs(threshold)
                    decline_severity = max(decline_severity, severity)

                    self.logger.info(f"급락 감지 ({period}): {decline_rate:.2f}% (기준: {threshold}%, 심각도: {severity:.1f})")

            return is_rapid_decline, decline_severity, decline_analysis

        except Exception as e:
            self.logger.error(f"급락 감지 실패: {e}")
            return False, 0, {}

    def detect_rapid_decline_5min(self, ticker, lookback_periods=12):
        """5분봉 기반 급격한 가격 하락 감지"""
        try:
            # 5분봉 데이터 조회
            df = self.api.get_ohlcv_data(ticker, 'minute5', lookback_periods + 5)
            if df is None or len(df) < lookback_periods + 2:
                self.logger.warning(f"5분봉 급락 감지용 데이터 부족: {ticker}")
                return False, 0, {}

            # 일관성을 위해 close 가격 사용
            prices = df['close']
            current_price = prices.iloc[-1]

            # 변동성 분석
            volatility_info = self.get_market_volatility(ticker)
            volatility_multiplier = _get_volatility_multiplier(volatility_info['volatility'])

            # 기간별 하락률 계산
            decline_analysis = {}

            periods = {
                '1_period': 1,  # 5분
                '3_period': 3,  # 15분
                '6_period': 6,  # 30분
                '12_period': 12  # 1시간
            }

            for period_name, period_count in periods.items():
                if len(prices) >= period_count + 1:
                    decline_rate = (current_price - prices.iloc[-(period_count + 1)]) / prices.iloc[-(period_count + 1)] * 100
                    decline_analysis[period_name] = decline_rate

            # 5분봉 기준 (변동성 고려)
            base_thresholds = {
                '1_period': -1.5,  # 5분에서 1.5%
                '3_period': -2.5,  # 15분에서 2.5%
                '6_period': -4.0,  # 30분에서 4%
                '12_period': -6.0  # 1시간에서 6%
            }

            # 변동성 및 코인별 조정
            coin_adjusted = get_coin_specific_thresholds(ticker, base_thresholds)
            final_thresholds = {}
            for period, threshold in coin_adjusted.items():
                final_thresholds[period] = threshold * volatility_multiplier

            # 급락 감지
            is_rapid_decline = False
            decline_severity = 0

            for period, decline_rate in decline_analysis.items():
                threshold = final_thresholds.get(period, 0)
                if decline_rate <= threshold:
                    is_rapid_decline = True
                    severity = abs(decline_rate) / abs(threshold)
                    decline_severity = max(decline_severity, severity)

                    self.logger.info(f"5분봉 급락 감지 ({period}): {decline_rate:.2f}% (기준: {threshold:.2f}%, 심각도: {severity:.1f})")

            return is_rapid_decline, decline_severity, decline_analysis

        except Exception as e:
            self.logger.error(f"5분봉 급락 감지 실패: {e}")
            return False, 0, {}

    def get_market_volatility(self, ticker):
        """시장 변동성 분석"""
        try:
            df = self.api.get_ohlcv_data(ticker, 'minute5', 20)
            if df is None or len(df) < 15:
                return {'volatility': 'MEDIUM', 'atr_ratio': 2.0}  # 기본값 조정

            # ATR (Average True Range) 계산
            high = df['high']
            low = df['low']
            close = df['close']

            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))

            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]

            # 현재가 대비 ATR 비율
            current_price = close.iloc[-1]
            atr_ratio = (atr / current_price) * 100 if current_price > 0 else 0

            # 변동성 등급 (5분봉 기준으로 조정)
            if atr_ratio > 4.0:  # 기존 5.0에서 낮춤
                volatility_level = 'VERY_HIGH'
            elif atr_ratio > 2.5:  # 기존 3.0에서 낮춤
                volatility_level = 'HIGH'
            elif atr_ratio > 1.2:  # 기존 1.5에서 낮춤
                volatility_level = 'MEDIUM'
            else:
                volatility_level = 'LOW'

            self.logger.info(f"시장 변동성: {volatility_level} (ATR 비율: {atr_ratio:.2f}%)")

            return {
                'volatility': volatility_level,
                'atr_ratio': atr_ratio
            }

        except Exception as e:
            self.logger.error(f"변동성 분석 실패: {e}")
            return {'volatility': 'MEDIUM', 'atr_ratio': 2.0}

    def should_delay_buy_gradual_approach(self, ticker, rsi_threshold=30):
        """급락 시 점진적 매수를 위한 지연 판단"""
        try:
            # 1단계: 급락 감지(5분봉으로 변경)
            is_declining, decline_severity, decline_details = self.detect_rapid_decline_5min(ticker)

            # 2단계: 시장 변동성 분석
            volatility_info = self.get_market_volatility(ticker)

            # 3단계: RSI 상태 확인 (보조 지표로 활용)
            rsi_state, current_rsi = self.get_rsi_state(ticker, rsi_threshold)

            # 4단계: 매도 압력 분석
            volume_data = self.volume_analyzer.analyze_sell_pressure(ticker)

            self.logger.info(f"급락분석 - 급락여부: {is_declining}, 심각도: {decline_severity:.1f}, RSI: {current_rsi:.1f}")

            # 매수 지연 결정 로직
            if not is_declining:
                # 급락이 아닌 경우: 일반적인 매도 압력 기준 적용
                return self._standard_selling_pressure_check(volume_data)

            # 급락 상황: 점진적 접근
            delay_score = 0

            # 급락 심각도에 따른 점수 (0-50)
            delay_score += min(decline_severity * 20, 50)

            # 변동성에 따른 점수 (0-20)
            volatility_scores = {
                'VERY_HIGH': 20,
                'HIGH': 15,
                'MEDIUM': 10,
                'LOW': 5
            }
            delay_score += volatility_scores.get(volatility_info['volatility'], 10)

            # 매도 압력에 따른 점수 (0-30)
            if volume_data:
                if volume_data['sell_buy_ratio'] > 3.0:
                    delay_score += 30
                elif volume_data['sell_buy_ratio'] > 2.0:
                    delay_score += 20
                elif volume_data['sell_buy_ratio'] > 1.5:
                    delay_score += 10

            # RSI 과매도 시 점수 감소 (매수 기회이므로)
            if current_rsi <= 20:
                delay_score -= 15  # 극심한 과매도
            elif current_rsi <= 30:
                delay_score -= 10  # 과매도

            self.logger.info(f"급락 상황 매수 지연 점수: {delay_score}")

            # 지연 결정 (70점 이상이면 지연)
            should_delay = delay_score >= 70

            if should_delay:
                self.logger.info(f"급락 감지 - 점진적 매수를 위해 대기 (점수: {delay_score})")
                self.logger.info(f"급락 상세: {decline_details}")
            else:
                self.logger.info(f"급락이지만 매수 조건 충족 (점수: {delay_score})")

            return should_delay

        except Exception as e:
            self.logger.error(f"점진적 매수 판단 실패: {e}")
            return False

    def get_rsi_state(self, ticker, rsi_threshold=30):
        """RSI 상태 확인 (보조 지표)"""
        try:
            df = self.api.get_ohlcv_data(ticker, 'minute5', 50)
            if df is None or len(df) < 20:
                return 'NEUTRAL', 50

            rsi_values = self.rsi_strategy.calculate_rsi(df['close'], 14)
            current_rsi = rsi_values.iloc[-1]

            if current_rsi <= 20:
                return 'EXTREME_OVERSOLD', current_rsi
            elif current_rsi <= rsi_threshold:
                return 'OVERSOLD', current_rsi
            elif current_rsi >= 80:
                return 'EXTREME_OVERBOUGHT', current_rsi
            elif current_rsi >= 70:
                return 'OVERBOUGHT', current_rsi
            else:
                return 'NEUTRAL', current_rsi

        except Exception as e:
            self.logger.error(f"RSI 상태 확인 실패: {e}")
            return 'NEUTRAL', 50

    def _standard_selling_pressure_check(self, volume_data):
        """일반 상황에서의 매도 압력 체크"""
        if not volume_data:
            return False

        # 표준 기준
        if volume_data['sell_buy_ratio'] > 2.5:
            self.logger.info(f"일반 상황 - 높은 매도 압력으로 매수 지연 (비율: {volume_data['sell_buy_ratio']:.2f})")
            return True

        return False