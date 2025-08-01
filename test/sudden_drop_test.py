import pyupbit
import sys
import pandas as pd


def get_market_volatility(ticker):
    """시장 변동성 분석"""
    try:
        df = pyupbit.get_ohlcv(ticker, 'minute5', 20)
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

        print(f"시장 변동성: {volatility_level} (ATR 비율: {atr_ratio:.2f}%)")

        return {
            'volatility': volatility_level,
            'atr_ratio': atr_ratio
        }

    except Exception as e:
        print(f"변동성 분석 실패: {e}")
        return {'volatility': 'MEDIUM', 'atr_ratio': 2.0}

def _get_volatility_multiplier(volatility_level):
    """변동성에 따른 기준 조정 배수"""
    multipliers = {
        'VERY_HIGH': 1.5,  # 고변동성일 때 기준 완화
        'HIGH': 1.2,
        'MEDIUM': 1.0,     # 기본값
        'LOW': 0.8         # 저변동성일 때 기준 강화
    }
    return multipliers.get(volatility_level, 1.0)


# tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-USDT', 'KRW-DOGE']
tickers = ['KRW-LAYER']
# all_tickers = pyupbit.get_tickers(fiat="KRW")
for ticker in tickers:
    interval='minute5'
    lookback_periods=5
    # 최근 데이터 조회 (5분봉 기준)

    df = pyupbit.get_ohlcv(ticker, interval, lookback_periods + 10)
    print(df)
    prices = df['low']
    current_price = prices.iloc[-1]

    # 코인별 변동성을 고려한 동적 기준 설정
    volatility_info = get_market_volatility(ticker)
    print(volatility_info)
    volatility_multiplier = _get_volatility_multiplier(volatility_info['volatility'])

    # 다양한 기간별 하락률 계산
    decline_analysis = {}

    # 1. 최근 5분봉 하락률
    if len(prices) >= 2:
        recent_decline = (current_price - prices.iloc[-2]) / prices.iloc[-2] * 100
        decline_analysis['1_period'] = recent_decline

    # 2. 최근 15분 하락률
    if len(prices) >= 4:
        three_period_decline = (current_price - prices.iloc[-4]) / prices.iloc[-4] * 100
        decline_analysis['3_period'] = three_period_decline

    # 3. 최근 30분 하락률
    if len(prices) >= 7:
        six_period_decline = (current_price - prices.iloc[-7]) / prices.iloc[-7] * 100
        decline_analysis['6_period'] = six_period_decline

    # 3. 최근 1시간 하락률
    if len(prices) >= 13:
        twelve_period_decline = (current_price - prices.iloc[-13]) / prices.iloc[-13] * 100
        decline_analysis['12_period'] = twelve_period_decline

    print('=' * 21 + ticker + '=' * 21)
    print(f'current_price(현재가격): {current_price}')
    print(f'recent_decline(최근 5분봉 하락률): {recent_decline}')
    print(f'three_period_decline(최근 15분 하락률): {three_period_decline}')
    print(f'six_period_decline(최근 30분 하락률): {six_period_decline}')
    print(f'twelve_period_decline(최근 1시간 하락률): {twelve_period_decline}')

    # 개선된 급락 기준 (변동성 고려)
    base_thresholds = {
        '1_period': -1.5,   # 5분에서 1.5% 하락
        '3_period': -2.5,   # 15분에서 2.5% 하락
        '6_period': -4.0,   # 30분에서 4% 하락
        '12_period': -6.0   # 1시간에서 6% 하락

    }

    # 변동성에 따른 동적 조정
    rapid_decline_thresholds = {}
    for period, base_threshold in base_thresholds.items():
        adjusted_threshold = base_threshold * volatility_multiplier
        rapid_decline_thresholds[period] = adjusted_threshold

    # 급락 감지
    is_rapid_decline = False
    decline_severity = 0

    for period, decline_rate in decline_analysis.items():
        print(f'period: {period}, decline_rate: {decline_rate}')
        threshold = rapid_decline_thresholds.get(period, 0)
        if decline_rate <= threshold:
            is_rapid_decline = True
            # 급락 심각도 계산 (기준 대비 얼마나 더 떨어졌는지)
            severity = abs(decline_rate) / abs(threshold)
            decline_severity = max(decline_severity, severity)

            print(f"급락 감지 ({period}): {decline_rate:.2f}% (기준: {threshold}%, 심각도: {severity:.1f})")

    print(f'=' * 50)