class VolumeBasedBuyStrategy:
    """매도 물량 분석 기반 매수 조정 전략"""

    def __init__(self, upbit_api, logger):
        self.api = upbit_api
        self.logger = logger

    def analyze_sell_pressure(self, ticker):
        """매도 압력 분석"""
        try:
            # 호가 정보 조회 (매도 물량)
            orderbook = self.api.get_orderbook(ticker)
            if not orderbook:
                self.logger.warning(f"호가 정보를 가져올 수 없어 매도 압력 분석을 건너뜁니다: {ticker}")
                return None

            # 매도 호가 물량 합계 (orderbook 구조에 맞게 수정)
            orderbook_units = orderbook.get('orderbook_units', [])
            if not orderbook_units:
                self.logger.warning(f"호가 단위 정보가 없습니다: {ticker}")
                return None

            sell_volume = sum([unit['ask_size'] for unit in orderbook_units if unit.get('ask_size')])
            buy_volume = sum([unit['bid_size'] for unit in orderbook_units if unit.get('bid_size')])

            # 매도/매수 비율 계산
            sell_buy_ratio = sell_volume / buy_volume if buy_volume > 0 else float('inf')

            # 최근 거래량 분석
            candles = self.api.get_candles_from_ticker(ticker, count=10)
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
                'volume_ratio': volume_ratio
            }

            self.logger.debug(f"매도 압력 분석 결과 ({ticker}): {result}")
            return result

        except Exception as e:
            self.logger.error(f"매도 압력 분석 실패: {e}")
            return None

    def get_market_sentiment(self, ticker):
        """시장 심리 분석 (추가 지표)"""
        try:
            orderbook = self.api.get_orderbook(ticker)
            if not orderbook:
                return None

            orderbook_units = orderbook.get('orderbook_units', [])
            if not orderbook_units:
                return None

            # 상위 5개 호가의 매도/매수 물량 비교
            top_asks = sum([unit['ask_size'] for unit in orderbook_units[:5] if unit.get('ask_size')])
            top_bids = sum([unit['bid_size'] for unit in orderbook_units[:5] if unit.get('bid_size')])

            # 스프레드 분석 (매도 1호가 - 매수 1호가)
            if orderbook_units:
                ask_price = orderbook_units[0].get('ask_price', 0)
                bid_price = orderbook_units[0].get('bid_price', 0)
                spread = ask_price - bid_price if ask_price and bid_price else 0
                spread_ratio = spread / bid_price if bid_price > 0 else 0
            else:
                spread_ratio = 0

            return {
                'top_ask_bid_ratio': top_asks / top_bids if top_bids > 0 else float('inf'),
                'spread_ratio': spread_ratio
            }

        except Exception as e:
            self.logger.error(f"시장 심리 분석 실패: {e}")
            return None