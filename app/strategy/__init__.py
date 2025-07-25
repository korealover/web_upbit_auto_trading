
def create_strategy(strategy_name, api, logger, **kwargs):
    """전략 객체 생성"""
    try:
        if strategy_name == 'bollinger':
            from app.strategy.bollinger import BollingerBandsStrategy
            return BollingerBandsStrategy(api, logger)

        elif strategy_name == 'bollinger_asymmetric':
            from app.strategy.bollinger_asymmetric import AsymmetricBollingerBandsStrategy
            strategy = AsymmetricBollingerBandsStrategy(api, logger)
            # 전략 객체에 설정값들을 저장
            strategy.window = kwargs.get('window', 20)
            strategy.buy_multiplier = kwargs.get('buy_multiplier', 3.0)
            strategy.sell_multiplier = kwargs.get('sell_multiplier', 2.0)
            return strategy

        elif strategy_name == 'rsi':
            from app.strategy.rsi import RSIStrategy
            return RSIStrategy(api, logger)

        elif strategy_name == 'adaptive':
            from app.strategy.adaptive import AdaptiveStrategy
            return AdaptiveStrategy(api, logger)

        elif strategy_name == 'ensemble':
            from app.strategy.ensemble import EnsembleStrategy
            return EnsembleStrategy(api, logger)

        elif strategy_name == 'volatility':
            from app.strategy.volatility import VolatilityBreakoutStrategy
            return VolatilityBreakoutStrategy(api, logger)

        else:
            logger.error(f"알 수 없는 전략: {strategy_name}")
            return None

    except ImportError as e:
        logger.error(f"전략 모듈 임포트 실패 ({strategy_name}): {e}")
        return None
    except Exception as e:
        logger.error(f"전략 생성 실패 ({strategy_name}): {e}")
        return None


def get_available_strategies():
    """사용 가능한 전략 목록 반환"""
    return {
        'bollinger': '볼린저 밴드 전략',
        'bollinger_asymmetric': '비대칭 볼린저 밴드 전략',
        'volatility': '변동성 돌파 전략',
        'rsi': 'RSI 전략',
        'adaptive': '어댑티브 전략',
        'ensemble': '앙상블 전략'
    }
