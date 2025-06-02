from app.strategy.bollinger import BollingerBandsStrategy
from app.strategy.volatility import VolatilityBreakoutStrategy

def create_strategy(strategy_name, upbit_api, logger):
    """전략 생성 팩토리 함수"""
    if strategy_name == 'volatility':
        return VolatilityBreakoutStrategy(upbit_api, logger)
    else:  # 기본값: 'bollinger'
        return BollingerBandsStrategy(upbit_api, logger)