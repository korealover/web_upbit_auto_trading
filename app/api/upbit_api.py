import pyupbit
from app.utils.caching import cache_with_timeout, invalidate_cache
from app.models import User
from config import Config
import time


class UpbitAPI:
    """업비트 API 래퍼 클래스"""

    def __init__(self, user_id, async_handler, logger):
        """
        초기화 - User 객체를 통해 암호화된 키를 자동 복호화

        Args:
            user_id: 사용자 ID
            async_handler: 비동기 핸들러
            logger: 로거 객체
        """
        self.user_id = user_id
        self.async_handler = async_handler
        self.logger = logger
        self.api_call_count = 0
        self.last_reset_time = 0

        # 사용자 정보 및 API 키 복호화
        self.user = User.query.get(user_id)
        if not self.user:
            raise ValueError(f"사용자를 찾을 수 없습니다: {user_id}")

        try:
            self.access_key, self.secret_key = self.user.get_upbit_keys()
            if not self.access_key or not self.secret_key:
                raise ValueError("업비트 API 키가 설정되지 않았습니다.")

            # 복호화된 키로 업비트 API 초기화
            self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
            self.logger.info(f"사용자 {self.user.username}의 업비트 API 초기화 완료")

        except Exception as e:
            self.logger.error(f"업비트 API 초기화 실패: {str(e)}")
            raise ValueError(f"업비트 API 초기화 실패: {str(e)}")

    @classmethod
    def create_from_user(cls, user, async_handler, logger):
        """
        User 객체로부터 UpbitAPI 인스턴스 생성

        Args:
            user: User 모델 인스턴스
            async_handler: 비동기 핸들러
            logger: 로거 객체

        Returns:
            UpbitAPI: 초기화된 UpbitAPI 인스턴스
        """
        return cls(user.id, async_handler, logger)

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

    def refresh_api_keys(self):
        """
        API 키 새로고침 (사용자가 키를 업데이트한 경우)
        """
        try:
            # 사용자 정보 새로고침
            self.user = User.query.get(self.user_id)
            self.access_key, self.secret_key = self.user.get_upbit_keys()

            if not self.access_key or not self.secret_key:
                raise ValueError("업비트 API 키가 설정되지 않았습니다.")

            # 새로운 키로 업비트 API 재초기화
            self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
            self.logger.info(f"사용자 {self.user.username}의 업비트 API 키 새로고침 완료")

        except Exception as e:
            self.logger.error(f"업비트 API 키 새로고침 실패: {str(e)}")
            raise ValueError(f"업비트 API 키 새로고침 실패: {str(e)}")

    def validate_api_keys(self):
        """
        API 키 유효성 검증

        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            # 간단한 API 호출로 키 유효성 검증
            balance = self.upbit.get_balance("KRW")
            if balance is None:
                return False, "API 키가 유효하지 않습니다."

            self.logger.info(f"사용자 {self.user.username}의 API 키 유효성 검증 성공")
            return True, None

        except Exception as e:
            error_msg = f"API 키 유효성 검증 실패: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

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


    def validate_ticker(self, ticker):
        """ticker 유효성 검증 - 캐싱 추가"""
        try:
            import pyupbit

            # 캐시된 티커 목록이 있는지 확인 (1시간마다 갱신)
            cache_key = 'valid_tickers'
            current_time = time.time()

            if not hasattr(self, '_ticker_cache') or not hasattr(self, '_ticker_cache_time'):
                self._ticker_cache = None
                self._ticker_cache_time = 0

            # 캐시가 없거나 1시간이 지났으면 새로 조회
            if (self._ticker_cache is None or
                    current_time - self._ticker_cache_time > 3600):
                self.logger.info("티커 목록 새로고침 중...")
                all_tickers = pyupbit.get_tickers(fiat="KRW")
                self._ticker_cache = set(all_tickers) if all_tickers else set()
                self._ticker_cache_time = current_time
                self.logger.info(f"총 {len(self._ticker_cache)}개의 유효한 KRW 티커 로드됨")

            if ticker not in self._ticker_cache:
                self.logger.warning(f"유효하지 않은 ticker: {ticker}")
                self.logger.info(f"사용 가능한 ticker 예시: {list(self._ticker_cache)[:10]}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"ticker 검증 실패: {e}")
            return False

    @cache_with_timeout(seconds=Config.CACHE_DURATION_PRICE)
    def get_current_price(self, ticker):
        """현재 가격 조회 - 티커 검증 추가"""
        try:
            # 먼저 ticker 형식 검증
            if not ticker or not isinstance(ticker, str):
                self.logger.error(f"잘못된 ticker 형식: {ticker}")
                return None

            # ticker 형식 정규화 (KRW- 접두사 확인)
            if not ticker.startswith('KRW-'):
                ticker = f'KRW-{ticker}'

            # 티커 유효성 검증
            if not self.validate_ticker(ticker):
                self.logger.error(f"유효하지 않은 ticker로 거래 중단: {ticker}")
                return None

            def safe_get_price():
                try:
                    import pyupbit
                    result = pyupbit.get_current_price(ticker)

                    # 결과 검증
                    if result is None:
                        self.logger.warning(f"가격 정보 없음: {ticker}")
                        return None

                    # 숫자인지 확인
                    if isinstance(result, (int, float)) and result > 0:
                        return float(result)

                    # 딕셔너리나 리스트 형태의 응답 처리
                    if isinstance(result, dict):
                        if 'trade_price' in result:
                            return float(result['trade_price'])
                        elif ticker in result:
                            return float(result[ticker])

                    if isinstance(result, list) and len(result) > 0:
                        if isinstance(result[0], dict) and 'trade_price' in result[0]:
                            return float(result[0]['trade_price'])

                    self.logger.warning(f"예상하지 못한 응답 형식: {ticker} -> {type(result)}: {result}")
                    return None

                except Exception as e:
                    self.logger.error(f"가격 조회 실패 ({ticker}): {e}")
                    return None

            # fetch_data를 통해 안전하게 호출
            price = self.fetch_data(safe_get_price)

            if price is None:
                self.logger.error(f"최종 가격 조회 실패: {ticker}")

            return price

        except Exception as e:
            self.logger.error(f"get_current_price 전체 오류 ({ticker}): {e}")
            return None

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

            # 전체 보유 코인의 가치 계산
            total_value = volume * current_price
            self.logger.info(f"전체 보유 코인 가치: {total_value:,.2f}원")

            # 매도할 수량 및 예상 금액 계산
            sell_volume = volume * portion
            estimated_value = sell_volume * current_price

            # 최소 매도 금액 확인 (5,000원)
            min_order_value = 5000
            self.logger.info(f"매도 계획: {portion * 100:.1f}% ({estimated_value:,.2f}원)")

            # 최소 주문 금액 미만일 경우 처리
            if estimated_value < min_order_value:
                self.logger.warning(f"매도 예상 금액({estimated_value:,.2f}원)이 최소 매도 금액({min_order_value}원)보다 작습니다.")

                # 전체 보유 가치가 최소 매도 금액보다 작은 경우
                if total_value < min_order_value:
                    error_msg = f"전체 보유 코인 가치({total_value:,.2f}원)가 최소 매도 금액({min_order_value}원)보다 작아서 매도할 수 없습니다."
                    self.logger.warning(error_msg)
                    return {"error": {"name": "insufficient_total_value", "message": error_msg}}

            # 너무 작은 수량 확인
            min_volume = 0.00000001  # 업비트 최소 거래량
            if sell_volume < min_volume:
                error_msg = f"매도 수량이 너무 적습니다: {sell_volume} < {min_volume}"
                self.logger.warning(error_msg)
                return {"error": {"name": "too_small_volume", "message": error_msg}}

            if 10000 > total_value > 5000:
                self.logger.info(f"최소 주문 금액 충족을 위해 전량 매도로 변경합니다.")
                sell_volume = volume * 1.0
                # 조정된 매도 금액 재계산
                estimated_value = sell_volume * current_price
                self.logger.info(f"조정된 매도 예상 금액: {estimated_value:,.2f}원")

            # 최종 매도 정보 로깅
            final_estimated_value = sell_volume * current_price
            final_portion = sell_volume / volume * 100

            self.logger.info(f"최종 매도 계획: {sell_volume:.8f} {ticker.split('-')[1]} ({final_portion:.1f}%, {final_estimated_value:,.2f}원)")

            # 매도 전 캐시 무효화
            invalidate_cache()

            # 예상 주문 금액이 5003원 이상일 경우 수수료 포함
            if estimated_value >= (min_order_value + 3):
                # 업비트 API 호출 및 결과 반환
                res = self.fetch_data(lambda: self.upbit.sell_market_order(ticker, sell_volume))
            else:
                # 이 경우는 논리적으로 발생하지 않아야 하므로 로그 추가
                self.logger.error(f"논리 오류: 최종 예상 금액({final_estimated_value:,.2f}원)이 최소 주문 금액({min_order_value}원)보다 작습니다.")
                res = {"error": {"name": "logic_error", "message": f"최종 예상 주문 금액({final_estimated_value:,.2f}원)이 최소 주문 금액({min_order_value}원)보다 작습니다."}}

            if res and 'error' in res:
                self.logger.error(f"분할 매도 주문 오류: {res} {estimated_value} {min_order_value}")
            elif res:
                self.logger.info(f"분할 매도 주문 성공: {res}")
                # 실제 매도된 비율 정보 추가
                actual_portion = sell_volume / volume
                res['actual_sell_portion'] = actual_portion
                res['original_portion'] = portion

            return res

        except Exception as e:
            error_msg = f"분할 매도 처리 중 예외 발생: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"error": {"name": "execution_error", "message": error_msg}}
