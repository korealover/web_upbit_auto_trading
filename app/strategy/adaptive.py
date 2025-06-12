import datetime
import pandas as pd


class AdaptiveStrategy:
    """시장 상황과 시간대에 적응하는 전략"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

        # 하위 전략들을 동적으로 임포트
        from app.strategy.volatility import VolatilityBreakoutStrategy
        from app.strategy.bollinger import BollingerBandsStrategy
        from app.strategy.rsi import RSIStrategy

        self.strategies = {
            'volatility': VolatilityBreakoutStrategy(upbit_api, logger),
            'bollinger': BollingerBandsStrategy(upbit_api, logger),
            'rsi': RSIStrategy(upbit_api, logger)
        }

    def detect_market_condition(self, ticker):
        """시장 상황 감지 (추세/횡보/고변동성)"""
        try:
            df = self.api.get_ohlcv_data(ticker, 'minute15', 50)
            if df is None or len(df) < 50:
                return 'ranging'  # 기본값

            # 변동성 계산 (단순화된 ATR)
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())

            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            current_atr = tr.rolling(14).mean().iloc[-1]
            avg_atr = tr.rolling(50).mean().iloc[-1]

            # 상대적 변동성
            if avg_atr > 0:
                relative_volatility = current_atr / avg_atr
            else:
                relative_volatility = 1.0

            # 추세 강도 계산
            df['ma20'] = df['close'].rolling(20).mean()
            df['ma50'] = df['close'].rolling(50).mean()

            ma20_slope = (df['ma20'].iloc[-1] - df['ma20'].iloc[-5]) / df['ma20'].iloc[-5] * 100

            self.logger.info(f"시장 분석 - 상대 변동성: {relative_volatility:.2f}, MA20 기울기: {ma20_slope:.2f}%")

            if relative_volatility > 1.5:
                return 'high_volatility'
            elif abs(ma20_slope) > 1.0:
                return 'trending'
            else:
                return 'ranging'

        except Exception as e:
            self.logger.error(f"시장 상황 감지 중 오류: {str(e)}")
            return 'ranging'

    def get_time_based_strategy(self):
        """시간대별 최적 전략 선택"""
        now = datetime.datetime.now()
        hour = now.hour

        # 한국 시장 활발 시간대 (오전 9시 ~ 12시)
        if 9 <= hour < 12:
            return 'volatility', 'korean_active'

        # 점심 시간대 (12시 ~ 14시) - 보수적 접근
        elif 12 <= hour < 14:
            return 'rsi', 'lunch_time'

        # 오후 활발 시간대 (14시 ~ 18시)
        elif 14 <= hour < 18:
            return 'bollinger', 'afternoon_active'

        # 저녁 시간대 (18시 ~ 22시) - 글로벌 시장 영향
        elif 18 <= hour < 22:
            return 'volatility', 'evening_global'

        # 야간 시간대 (22시 ~ 9시) - 미국 시장 영향
        else:
            return 'rsi', 'night_us'

    def generate_signal(self, ticker):
        """어댑티브 매매 신호 생성"""
        try:
            # 시장 상황 분석
            market_condition = self.detect_market_condition(ticker)

            # 시간대별 전략 선택
            time_strategy, time_period = self.get_time_based_strategy()

            self.logger.info(f"어댑티브 전략 - 시장상황: {market_condition}, 시간대: {time_period}, 선택전략: {time_strategy}")

            # 시장 상황에 따른 전략 오버라이드
            if market_condition == 'high_volatility':
                # 고변동성 시장에서는 볼린저 밴드 사용 (안전한 접근)
                prices = self.api.get_ohlcv_data(ticker, 'minute15', 30)
                if prices is not None and len(prices) >= 30:
                    signal = self.strategies['bollinger'].generate_signal(ticker, prices['close'], 20, 2.5)
                    self.logger.info("고변동성 시장: 볼린저 밴드 전략 적용")
                else:
                    signal = 'HOLD'

            elif market_condition == 'trending':
                # 추세 시장에서는 변동성 돌파 전략 사용
                signal = self.strategies['volatility'].generate_volatility_signal(ticker, k=0.5)
                self.logger.info("추세 시장: 변동성 돌파 전략 적용")

            else:  # ranging market
                # 횡보 시장에서는 시간대별 전략 사용
                if time_strategy == 'volatility':
                    signal = self.strategies['volatility'].generate_volatility_signal(ticker, k=0.3)
                elif time_strategy == 'bollinger':
                    prices = self.api.get_ohlcv_data(ticker, 'minute15', 30)
                    if prices is not None and len(prices) >= 30:
                        signal = self.strategies['bollinger'].generate_signal(ticker, prices['close'], 20, 2.0)
                    else:
                        signal = 'HOLD'
                else:  # rsi
                    signal = self.strategies['rsi'].generate_signal(ticker, period=14, oversold=30, overbought=70)

                self.logger.info(f"횡보 시장: {time_strategy} 전략 적용 ({time_period})")

            return signal

        except Exception as e:
            self.logger.error(f"어댑티브 전략 신호 생성 중 오류: {str(e)}")
            return 'HOLD'