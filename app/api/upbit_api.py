import pyupbit
from app.utils.caching import cache_with_timeout, invalidate_cache
from config import Config


class UpbitAPI:
    """업비트 API 래퍼 클래스"""

    def __init__(self, access_key, secret_key, async_handler, logger):
        """초기화"""
        self.upbit = pyupbit.Upbit(access_key, secret_key)
        self.async_handler = async_handler
        self.logger = logger
        self.api_call_count = 0
        self.last_reset_time = 0

    def _log_api_call(self):
        """API 호출 모니터링"""
        import time
        self.api_call_count += 1
        current_time = time.time()

        # 1시간마다 API 호출 횟수 로깅 및 초기화
        if current_time - self.last_reset_time >= 3600:
            self.logger.info(f"API 호출 횟수 (지난 1시간): {self.api_call_count}")
            self.api_call_count = 0
            self.last_reset_time = current_time

    def fetch_data(self, fetch_func, max_retries=5, delay=0.5, backoff_factor=2):
        """데이터 가져오기 - 지수 백오프 추가"""
        result = self.async_handler.run_sync(
            fetch_func,
            max_retries=max_retries,
            delay=delay,
            logger=self.logger,
            backoff_factor=backoff_factor
        )
        self._log_api_call()
        return result

    @cache_with_timeout(seconds=Config.CACHE_DURATION_PRICE)
    def get_current_price(self, ticker):
        """현재가 조회"""
        price = self.fetch_data(lambda: pyupbit.get_current_price(ticker))
        self.logger.debug(f"{ticker} 현재가: {price}")
        return price

    @cache_with_timeout(seconds=Config.CACHE_DURATION_BALANCE)
    def get_balance_cash(self):
        """현금 잔고 조회"""
        balance = self.fetch_data(lambda: self.upbit.get_balance("KRW"))
        self.logger.debug(f"보유 현금: {balance} KRW")
        return balance

    @cache_with_timeout(seconds=Config.CACHE_DURATION_BALANCE)
    def get_balance_coin(self, ticker):
        """코인 잔고 조회"""
        balance = self.fetch_data(lambda: self.upbit.get_balance(ticker))
        self.logger.debug(f"{ticker} 보유량: {balance}")
        return balance

    @cache_with_timeout(seconds=Config.CACHE_DURATION_PRICE_AVG)
    def get_buy_avg(self, ticker):
        """평균 매수가 조회"""
        avg_price = self.fetch_data(lambda: self.upbit.get_avg_buy_price(ticker))
        self.logger.debug(f"{ticker} 평균 매수가: {avg_price}")
        return avg_price

    def get_order_info(self, ticker):
        """주문 정보 조회"""
        try:
            orders = self.fetch_data(lambda: self.upbit.get_order(ticker))
            if orders and len(orders) > 0 and "error" not in orders[0]:
                self.logger.debug(f"{ticker} 주문 정보: {orders[-1]}")
                return orders[-1]
        except Exception as e:
            self.logger.error(f"주문 정보 조회 실패: {str(e)}")
        return None

    def order_buy_market(self, ticker, buy_amount):
        """시장가 매수"""
        if buy_amount < 5000:
            self.logger.warning(f"매수 금액이 5000원 미만입니다: {buy_amount}")
            return 0

        self.logger.info(f"시장가 매수 시도: {ticker}, {buy_amount:,.2f}원")

        # 매수 전 캐시 무효화
        invalidate_cache()

        res = self.fetch_data(lambda: self.upbit.buy_market_order(ticker, buy_amount))

        if res and 'error' in res:
            self.logger.error(f"매수 주문 오류: {res}")
            res = 0
        elif res:
            self.logger.info(f"매수 주문 성공: {res}")

        return res

    def order_sell_market(self, ticker, volume):
        """시장가 매도"""
        self.logger.info(f"시장가 매도 시도: {ticker}, {volume}")

        # 매도 전 캐시 무효화
        invalidate_cache()

        res = self.fetch_data(lambda: self.upbit.sell_market_order(ticker, volume))

        if res and 'error' in res:
            self.logger.error(f"매도 주문 오류: {res}")
            res = 0
        elif res:
            self.logger.info(f"매도 주문 성공: {res}")

        return res

    @cache_with_timeout(seconds=Config.CACHE_DURATION_OHLCV)
    def get_ohlcv_data(self, ticker, interval, count):
        """OHLCV 데이터 조회"""
        data = self.fetch_data(lambda: pyupbit.get_ohlcv(ticker, interval=interval, count=count))
        return data

    def order_sell_market_partial(self, ticker, portion):
        """시장가 분할 매도

        Args:
            ticker (str): 매도할 코인 티커
            portion (float): 매도할 비율 (0.0 ~ 1.0)

        Returns:
            dict: 주문 결과 또는 오류 정보가 포함된 딕셔너리
        """
        try:
            if portion <= 0 or portion > 1:
                error_msg = f"매도 비율은 0보다 크고 1 이하여야 합니다: {portion}"
                self.logger.error(error_msg)
                return {"error": {"name": "invalid_portion", "message": error_msg}}

            # 현재 보유량 확인
            volume = self.get_balance_coin(ticker)
            if not volume or volume <= 0:
                error_msg = f"{ticker} 보유량이 없습니다."
                self.logger.warning(error_msg)
                return {"error": {"name": "no_balance", "message": error_msg}}

            # 현재가 확인
            current_price = self.get_current_price(ticker)
            if not current_price:
                error_msg = f"{ticker} 현재가를 가져올 수 없습니다."
                self.logger.error(error_msg)
                return {"error": {"name": "price_fetch_error", "message": error_msg}}

            # 매도할 수량 계산
            sell_volume = volume * portion

            # 최소 주문 금액 확인 (5,000원)
            min_order_value = 5000
            estimated_value = sell_volume * current_price

            # 최소 주문 금액 미만일 경우 자동 조정
            if estimated_value < min_order_value:
                self.logger.warning(f"매도 예상 금액({estimated_value:,.2f}원)이 최소 주문 금액({min_order_value}원)보다 작습니다.")

                # 최소 주문 금액을 충족하는 매도 비율 계산
                min_sell_portion = min(min_order_value / (volume * current_price), 1.0)

                # 최소 주문 금액을 충족하는 비율이 전체의 98% 이상이면 전량 매도로 전환
                if min_sell_portion >= 0.98:
                    self.logger.info(f"최소 주문 금액을 충족하기 위해 전량 매도로 변경합니다.")
                    sell_volume = volume  # 전량 매도
                else:
                    # 최소 주문 금액을 충족하는 비율로 조정
                    new_sell_volume = volume * min_sell_portion
                    self.logger.info(f"최소 주문 금액 충족을 위해 매도 수량을 {sell_volume:.8f}에서 {new_sell_volume:.8f}로 조정합니다.")
                    sell_volume = new_sell_volume

            # 너무 작은 수량 확인
            min_volume = 0.00000001  # 업비트 최소 거래량
            if sell_volume < min_volume:
                error_msg = f"매도 수량이 너무 적습니다: {sell_volume} < {min_volume}"
                self.logger.warning(error_msg)
                return {"error": {"name": "too_small_volume", "message": error_msg}}

            self.logger.info(f"분할 매도 시도: {ticker}, {sell_volume} (원래 비율: {portion * 100:.1f}%)")

            # 매도 전 캐시 무효화
            invalidate_cache()

            # 업비트 API 호출 및 결과 반환
            res = self.fetch_data(lambda: self.upbit.sell_market_order(ticker, sell_volume))

            if res and 'error' in res:
                self.logger.error(f"분할 매도 주문 오류: {res}")
            elif res:
                self.logger.info(f"분할 매도 주문 성공: {res}")

            # 원본 응답 그대로 반환 (오류 포함)
            return res

        except Exception as e:
            error_msg = f"분할 매도 처리 중 예외 발생: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"error": {"name": "execution_error", "message": error_msg}}
