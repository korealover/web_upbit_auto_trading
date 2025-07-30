import pyupbit

# 매수 시 매수/매도 물량 확인 테스트
tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-USDT', 'KRW-DOGE']
# all_tickers = pyupbit.get_tickers(fiat="KRW")
for ticker in tickers:
    # ticker = 'KRW-ETH'
    print('='*21 + ticker + '='*21)
    orderbook = pyupbit.get_orderbook(ticker)
    # print(f'어리1 {orderbook}')
    orderbook_units = orderbook.get('orderbook_units', [])
    # print(f'어리2 {orderbook_units}')
    sell_volume = sum([unit['ask_size'] for unit in orderbook_units if unit.get('ask_size')])
    buy_volume = sum([unit['bid_size'] for unit in orderbook_units if unit.get('bid_size')])
    print(f'매도 압력: {sell_volume}')
    print(f'매수 압력: {buy_volume}')
    # 매도/매수 비율 계산
    sell_buy_ratio = sell_volume / buy_volume if buy_volume > 0 else float('inf')
    print(f'매도/매수 비율: {sell_buy_ratio}')

    # 상위 5개 호가의 매도/매수 물량 비교
    top_asks = sum([unit['ask_size'] for unit in orderbook_units[:5] if unit.get('ask_size')])
    top_bids = sum([unit['bid_size'] for unit in orderbook_units[:5] if unit.get('bid_size')])
    print(f'상위 5개 매도 압력: {top_asks}')
    print(f'상위 5개 매수 압력: {top_bids}')

    # 스프레드 분석 (매도 1호가 - 매수 1호가)
    if orderbook_units:
        ask_price = orderbook_units[0].get('ask_price', 0)
        bid_price = orderbook_units[0].get('bid_price', 0)
        spread = ask_price - bid_price if ask_price and bid_price else 0
        spread_ratio = spread / bid_price if bid_price > 0 else 0
    else:
        spread_ratio = 0

    print(f'스프레드: {spread_ratio}')

    df = pyupbit.get_ohlcv(ticker, interval="minute5", count=10)

    if df is not None or not df.empty:
        candles = []
        for index, row in df.iterrows():
            candle = {
                'candle_date_time_kst': index.strftime('%Y-%m-%dT%H:%M:%S'),
                'opening_price': float(row['open']),
                'high_price': float(row['high']),
                'low_price': float(row['low']),
                'trade_price': float(row['close']),
                'candle_acc_trade_volume': float(row['volume']),
                'timestamp': int(index.timestamp() * 1000)
            }
            candles.append(candle)

        # 최신 데이터가 먼저 오도록 역순 정렬
        candles.reverse()
        volume_ratio = 1

        if candles and len(candles) > 1:
            recent_volumes = [candle['candle_acc_trade_volume'] for candle in candles[:5]]  # 최근 5개
            if recent_volumes:
                avg_volume = sum(recent_volumes) / len(recent_volumes)
                current_volume = recent_volumes[0]
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        result = {
            'sell_volume': sell_volume,
            'buy_volume': buy_volume,
            'sell_buy_ratio': sell_buy_ratio,
            'volume_ratio': volume_ratio,
            'top_ask_bid_ratio': top_asks / top_bids if top_bids > 0 else float('inf'),
            'spread_ratio': spread_ratio
        }

        print(f'=' * 50)