from app.strategy.rsi import RSIStrategy
from app.strategy.volume_base_buy import VolumeBasedBuyStrategy


class RSIVolumeIntegratedStrategy:
    """급락 감지 및 점진적 매수 전략"""

    def __init__(self, upbit_api, logger):
        self.api = upbit_api
        self.logger = logger
        self.rsi_strategy = RSIStrategy(upbit_api, logger)
        self.volume_analyzer = VolumeBasedBuyStrategy(upbit_api, logger)

    def detect_rapid_decline(self, ticker, lookback_periods=5):
        """급격한 가격 하락 감지"""
        try:
            # 최근 데이터 조회 (5분봉 기준)
            df = self.api.get_ohlcv_data(ticker, 'minute5', lookback_periods + 10)
            if df is None or len(df) < lookback_periods + 5:
                self.logger.warning(f"급락 감지용 데이터 부족: {ticker}")
                return False, 0, {}

            prices = df['close']
            current_price = prices.iloc[-1]

            # 다양한 기간별 하락률 계산
            decline_analysis = {}

            # 1. 최근 5분봉 하락률
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

            # 급락 기준 설정 (코인별로 조정 가능)
            rapid_decline_thresholds = {
                '1_period': -3.0,  # 1봉에서 3% 이상 하락
                '3_period': -8.0,  # 3봉에서 8% 이상 하락
                '5_period': -15.0  # 5봉에서 15% 이상 하락
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

    def get_market_volatility(self, ticker):
        """시장 변동성 분석"""
        try:
            df = self.api.get_ohlcv_data(ticker, 'minute5', 20)
            if df is None or len(df) < 15:
                return {'volatility': 'LOW', 'atr_ratio': 1.0}

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

            # 변동성 등급
            if atr_ratio > 5.0:
                volatility_level = 'VERY_HIGH'
            elif atr_ratio > 3.0:
                volatility_level = 'HIGH'
            elif atr_ratio > 1.5:
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
            # 1단계: 급락 감지
            is_declining, decline_severity, decline_details = self.detect_rapid_decline(ticker)

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
            self.logger.info(f"일반 상황 - 높은 매도 압력으로 매수 지연")
            return True

        return False