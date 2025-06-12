import datetime


class EnsembleStrategy:
    """여러 전략을 결합한 앙상블 전략"""

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

    def generate_signal(self, ticker, weights=None):
        """앙상블 매매 신호 생성

        Args:
            ticker (str): 티커 심볼
            weights (dict): 각 전략의 가중치 (기본값: 균등 가중)

        Returns:
            str: 'BUY', 'SELL', 'HOLD' 중 하나의 신호
        """
        try:
            # 기본 가중치 설정
            if weights is None:
                # 시간대별로 가중치 조정
                now = datetime.datetime.now()
                hour = now.hour

                if 9 <= hour < 12:  # 한국 아침 시간대
                    weights = {'volatility': 0.5, 'bollinger': 0.3, 'rsi': 0.2}
                elif 14 <= hour < 18:  # 오후 시간대
                    weights = {'volatility': 0.3, 'bollinger': 0.5, 'rsi': 0.2}
                else:  # 기타 시간대
                    weights = {'volatility': 0.3, 'bollinger': 0.3, 'rsi': 0.4}

            signals = {}
            signal_scores = {'BUY': 1, 'HOLD': 0, 'SELL': -1}
            total_score = 0
            valid_strategies = 0

            # 각 전략별 신호 수집
            for name, strategy in self.strategies.items():
                try:
                    if name == 'volatility':
                        signals[name] = strategy.generate_volatility_signal(ticker, k=0.5)
                    elif name == 'bollinger':
                        prices = self.api.get_ohlcv_data(ticker, 'minute15', 30)
                        if prices is not None and len(prices) >= 30:
                            signals[name] = strategy.generate_signal(ticker, prices['close'], 20, 2)
                        else:
                            signals[name] = 'HOLD'
                    else:  # rsi
                        signals[name] = strategy.generate_signal(ticker)

                    # 가중치 적용하여 점수 계산
                    total_score += signal_scores[signals[name]] * weights[name]
                    valid_strategies += 1

                except Exception as e:
                    self.logger.warning(f"{name} 전략 실행 중 오류: {str(e)}")
                    signals[name] = 'HOLD'

            if valid_strategies == 0:
                self.logger.error("모든 전략 실행 실패")
                return 'HOLD'

            self.logger.info(f"앙상블 전략 - 신호: {signals}")
            self.logger.info(f"가중치: {weights}")
            self.logger.info(f"종합 점수: {total_score:.2f}")

            # 추가 안전장치: 최소 2개 전략이 같은 방향일 때만 매매
            buy_count = sum(1 for signal in signals.values() if signal == 'BUY')
            sell_count = sum(1 for signal in signals.values() if signal == 'SELL')

            # 종합 점수와 신호 일치도를 모두 고려
            if total_score > 0.4 and buy_count >= 2:
                self.logger.info(f"앙상블 매수 신호 (점수: {total_score:.2f}, 매수 신호 수: {buy_count})")
                return 'BUY'
            elif total_score < -0.4 and sell_count >= 2:
                self.logger.info(f"앙상블 매도 신호 (점수: {total_score:.2f}, 매도 신호 수: {sell_count})")
                return 'SELL'
            else:
                self.logger.info(f"앙상블 홀드 신호 (점수: {total_score:.2f})")
                return 'HOLD'

        except Exception as e:
            self.logger.error(f"앙상블 전략 신호 생성 중 오류: {str(e)}")
            return 'HOLD'