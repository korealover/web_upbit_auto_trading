from app.strategy.bollinger import BollingerBandsStrategy
from app.strategy.volatility import VolatilityBreakoutStrategy
from app.strategy.rsi import RSIStrategy
from app.strategy.adaptive import AdaptiveStrategy
from app.strategy.ensemble import EnsembleStrategy


def create_strategy(strategy_name, upbit_api, logger):
    """전략 생성 팩토리 함수"""
    if strategy_name == 'volatility':
        return VolatilityBreakoutStrategy(upbit_api, logger)
    elif strategy_name == 'rsi':
        return RSIStrategy(upbit_api, logger)
    elif strategy_name == 'adaptive':
        return AdaptiveStrategy(upbit_api, logger)
    elif strategy_name == 'ensemble':
        return EnsembleStrategy(upbit_api, logger)
    else:  # 기본값: 'bollinger'
        return BollingerBandsStrategy(upbit_api, logger)


def get_available_strategies():
    """사용 가능한 전략 목록 반환"""
    return {
        'bollinger': '볼린저 밴드 전략',
        'volatility': '변동성 돌파 전략',
        'rsi': 'RSI 전략',
        'adaptive': '어댑티브 전략',
        'ensemble': '앙상블 전략'
    }
