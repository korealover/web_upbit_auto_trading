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
            # 세션 분리 문제 해결을 위해 사용자 정보를 다시 조회
            from app import db
            user = db.session.get(User, self.user_id)
            if not user:
                raise ValueError(f"사용자 ID {self.user_id}를 찾을 수 없습니다.")

            self.user = user
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
            # API 키가 설정되어 있는지 먼저 확인
            if not hasattr(self, 'upbit') or self.upbit is None:
                return False, "업비트 API 객체가 초기화되지 않았습니다."

            if not self.access_key or not self.secret_key:
                return False, "API 키가 설정되지 않았습니다."

            # 간단한 API 호출로 키 유효성 검증 - fetch_data 사용으로 안정성 향상
            balance = self.fetch_data(
                lambda: self.upbit.get_balance("KRW"),
                max_retries=2,  # 재시도 횟수 줄임
                delay=1.0,  # 재시도 간격 늘림
                backoff_factor=1.5
            )

            # balance가 None이거나 숫자가 아닌 경우 체크
            if balance is None:
                return False, "API 키가 유효하지 않거나 서버 응답이 없습니다."

            # balance가 문자열로 반환되는 경우도 있으므로 타입 체크
            try:
                float(balance)
            except (TypeError, ValueError):
                self.logger.warning(f"예상하지 못한 balance 응답: {type(balance)} - {balance}")
                return False, "API 응답 형식이 올바르지 않습니다."

            # Flask 애플리케이션 컨텍스트에서 데이터베이스 접근
            from app import db, app
            username = f"ID:{self.user_id}"  # 기본값 설정

            try:
                with app.app_context():
                    user = db.session.get(User, self.user_id)
                    if user:
                        username = user.username
            except Exception as db_error:
                # 데이터베이스 접근 실패해도 API 키 검증은 계속 진행
                self.logger.warning(f"사용자 정보 조회 실패: {str(db_error)}")

            self.logger.info(f"사용자 {username}의 API 키 유효성 검증 성공 (잔고: {balance})")
            return True, None

        except Exception as e:
            error_msg = f"API 키 유효성 검증 실패: {str(e)}"
            self.logger.error(error_msg, exc_info=True)

            # 구체적인 에러 타입에 따른 메시지 개선
            if "Invalid API key" in str(e) or "invalid_access_key" in str(e):
                return False, "잘못된 API 키입니다. 키를 다시 확인해주세요."
            elif "permission" in str(e).lower():
                return False, "API 키 권한이 부족합니다. 자산 조회 권한을 확인해주세요."
            elif "network" in str(e).lower() or "timeout" in str(e).lower():
                return False, "네트워크 연결 문제입니다. 잠시 후 다시 시도해주세요."
            elif "rate limit" in str(e).lower():
                return False, "API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
            else:
                return False, f"API 키 검증 중 오류 발생: {str(e)}"

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
        """ticker 유효성 검증 - 개선된 버전"""
        try:
            import pyupbit

            # 캐시된 티커 목록이 있는지 확인 (1시간마다 갱신)
            current_time = time.time()

            if not hasattr(self, '_ticker_cache') or not hasattr(self, '_ticker_cache_time'):
                self._ticker_cache = None
                self._ticker_cache_time = 0

            # 캐시가 없거나 1시간이 지났으면 새로 조회
            if (self._ticker_cache is None or
                    current_time - self._ticker_cache_time > 3600):
                try:
                    self.logger.info("티커 목록 새로고침 중...")
                    all_tickers = pyupbit.get_tickers(fiat="KRW")

                    if all_tickers and len(all_tickers) > 0:
                        self._ticker_cache = set(all_tickers)
                        self._ticker_cache_time = current_time
                        self.logger.info(f"총 {len(self._ticker_cache)}개의 유효한 KRW 티커 로드됨")
                    else:
                        self.logger.warning("티커 목록 조회 결과가 비어있습니다.")
                        # 기존 캐시가 있다면 그대로 사용
                        if self._ticker_cache is None:
                            return False

                except Exception as e:
                    self.logger.error(f"티커 목록 조회 실패: {e}")
                    # 기존 캐시가 있다면 그대로 사용
                    if self._ticker_cache is None:
                        return False

            if ticker not in self._ticker_cache:
                self.logger.warning(f"유효하지 않은 ticker: {ticker}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"ticker 검증 실패: {e}")
            return False

    @cache_with_timeout(seconds=Config.CACHE_DURATION_PRICE)
    def get_current_price(self, ticker):
        """현재 가격 조회 - 안전성 및 로깅 개선"""
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
                # 사용 가능한 유사한 티커 제안
                self._suggest_similar_tickers(ticker)
                return None

            def safe_get_price():
                try:
                    import pyupbit
                    result = pyupbit.get_current_price(ticker)

                    # 결과 검증
                    if result is None:
                        self.logger.warning(f"가격 정보 없음: {ticker}")
                        return None

                    # 0 또는 음수 체크
                    if isinstance(result, (int, float)):
                        if result <= 0:
                            self.logger.warning(f"비정상적인 가격: {ticker} -> {result}")
                            return None
                        return float(result)

                    # 딕셔너리나 리스트 형태의 응답 처리
                    if isinstance(result, dict):
                        price = None
                        if 'trade_price' in result:
                            price = result['trade_price']
                        elif ticker in result:
                            price = result[ticker]

                        if price is not None and price > 0:
                            return float(price)

                    if isinstance(result, list) and len(result) > 0:
                        if isinstance(result[0], dict) and 'trade_price' in result[0]:
                            price = result[0]['trade_price']
                            if price is not None and price > 0:
                                return float(price)

                    self.logger.warning(f"예상하지 못한 응답 형식 또는 비정상적인 가격: {ticker} -> {type(result)}: {result}")
                    return None

                except Exception as e:
                    self.logger.error(f"가격 조회 API 호출 실패 ({ticker}): {e}")
                    return None

            # fetch_data를 통해 안전하게 호출
            price = self.fetch_data(safe_get_price, max_retries=3)

            if price is None:
                self.logger.error(f"가격 조회 실패 ({ticker}): 최종 결과가 None")
            elif price <= 0:
                self.logger.error(f"가격 조회 실패 ({ticker}): 비정상적인 가격 {price}")
                return None

            return price

        except Exception as e:
            self.logger.error(f"get_current_price 전체 오류 ({ticker}): {e}")
            return None

    def _suggest_similar_tickers(self, invalid_ticker):
        """유사한 티커 제안"""
        try:
            if hasattr(self, '_ticker_cache') and self._ticker_cache:
                # 입력된 티커에서 코인 이름 추출
                coin_name = invalid_ticker.replace('KRW-', '') if invalid_ticker.startswith('KRW-') else invalid_ticker

                # 유사한 티커 찾기
                similar = [t for t in self._ticker_cache if coin_name.lower() in t.lower()]

                if similar:
                    self.logger.info(f"유사한 티커 제안: {similar[:5]}")  # 최대 5개만 제안
                else:
                    # 랜덤하게 몇 개 제안
                    sample_tickers = list(self._ticker_cache)[:10]
                    self.logger.info(f"사용 가능한 티커 예시: {sample_tickers}")

        except Exception as e:
            self.logger.debug(f"티커 제안 중 오류: {e}")

    @cache_with_timeout(seconds=Config.CACHE_DURATION_BALANCE)
    def get_balance_cash(self):
        """현금 잔고 조회 - 안전성 강화"""
        try:
            balance = self.fetch_data(lambda: self.upbit.get_balance("KRW"))

            if balance is None:
                self.logger.warning("현금 잔고 조회 결과가 None입니다.")
                return 0.0

            # 타입 검증 및 변환
            if isinstance(balance, (int, float)):
                result = float(balance)
            elif isinstance(balance, str):
                try:
                    result = float(balance)
                except ValueError:
                    self.logger.error(f"현금 잔고를 숫자로 변환할 수 없습니다: {balance}")
                    return 0.0
            else:
                self.logger.error(f"예상하지 못한 현금 잔고 타입: {type(balance)} - {balance}")
                return 0.0

            self.logger.debug(f"보유 현금: {result:,.2f} KRW")
            return result

        except Exception as e:
            self.logger.error(f"현금 보유량 조회 중 오류 (사용자: {self.user_id}): {str(e)}")
            return 0.0

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


    def get_orderbook(self, ticker):
        """호가 정보 조회"""
        try:
            self._log_api_call()
            # pyupbit를 사용하여 호가 정보 조회
            orderbook = pyupbit.get_orderbook(ticker)
            if orderbook is None:
                self.logger.warning(f"호가 정보를 가져올 수 없습니다: {ticker}")
                return None
            return orderbook
        except Exception as e:
            self.logger.error(f"호가 정보 조회 실패 ({ticker}): {str(e)}")
            return None

    def get_candles_from_ticker(self, ticker, interval="minute5", count=200):
        """캔들 데이터 조회"""
        try:
            self._log_api_call()
            # pyupbit를 사용하여 캔들 데이터 조회
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is None or df.empty:
                self.logger.warning(f"캔들 데이터를 가져올 수 없습니다: {ticker}")
                return None

            # DataFrame을 딕셔너리 리스트로 변환
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
            return candles

        except Exception as e:
            self.logger.error(f"캔들 데이터 조회 실패 ({ticker}): {str(e)}")
            return None

    def get_candles_data(self, ticker, interval='minute5', count=200):
        """캔들 데이터 가져오기 (RSI 계산용)"""
        try:
            self._log_api_call()

            # interval 매개변수 처리
            if interval.startswith('minute'):
                period = int(interval.replace('minute', '')) if interval != 'minute' else 1
                df = self.get_ohlcv_data(ticker, interval, count)
            else:
                df = self.get_ohlcv_data(ticker, interval, count)

            if df is None or len(df) == 0:
                self.logger.warning(f"캔들 데이터가 없습니다: {ticker}")
                return []

            # 데이터 형식 변환 (rsi_selling_pressure.py에서 기대하는 형식으로)
            formatted_candles = []
            for idx, row in df.iterrows():
                formatted_candles.append({
                    'trade_price': row['close'],
                    'high_price': row['high'],
                    'low_price': row['low'],
                    'opening_price': row['open'],
                    'timestamp': idx,
                    'candle_acc_trade_volume': row['volume']
                })

            self.logger.info(f"캔들 데이터 {len(formatted_candles)}개 조회 완료: {ticker}")
            return formatted_candles

        except Exception as e:
            self.logger.error(f"캔들 데이터 조회 실패: {ticker}, 오류: {e}")
            return []

    @cache_with_timeout(seconds=Config.CACHE_DURATION_PRICE)
    def get_ticker(self, ticker):
        """티커 정보 조회 (24시간 거래량, 거래대금 등)"""
        try:
            self._log_api_call()

            # OHLCV 데이터에서 24시간 정보 추출
            import pyupbit

            # 24시간 데이터 가져오기 (1일봉 2개 - 어제, 오늘)
            df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
            if df is None or len(df) == 0:
                self.logger.warning(f"OHLCV 데이터를 가져올 수 없습니다: {ticker}")
                return None

            # 현재가 조회
            current_price = self.get_current_price(ticker)
            if not current_price:
                self.logger.warning(f"현재가를 가져올 수 없습니다: {ticker}")
                return None

            # 최신 데이터 (오늘)
            latest = df.iloc[-1]

            # 어제 종가 (변화율 계산용)
            prev_close = df.iloc[-2]['close'] if len(df) > 1 else latest['open']

            # 24시간 거래량 및 거래대금 계산
            volume_24h = latest['volume']
            trade_value_24h = volume_24h * current_price

            # 변화율 계산
            change_rate = ((current_price - prev_close) / prev_close) if prev_close > 0 else 0

            # 필요한 정보 반환
            return {
                'market': ticker,
                'trade_price': current_price,
                'acc_trade_volume_24h': volume_24h,
                'acc_trade_price_24h': trade_value_24h,
                'change_rate': change_rate,
                'prev_closing_price': prev_close,
                'high_price': latest['high'],
                'low_price': latest['low'],
                'opening_price': latest['open']
            }

        except Exception as e:
            self.logger.error(f"티커 정보 조회 실패 ({ticker}): {str(e)}")
            return None
