import pandas as pd


class RSIStrategy:
    """RSI 지표 기반 트레이딩 전략"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

    def calculate_rsi(self, prices, period=14):
        """RSI 계산 - 안전한 버전"""
        try:
            if len(prices) < period + 1:
                self.logger.warning(f"RSI 계산을 위한 데이터 부족: {len(prices)}개 (최소 {period + 1}개 필요)")
                return pd.Series([50] * len(prices), index=prices.index)

            delta = prices.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            # 첫 번째 평균은 단순 평균 사용
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()

            # RSI 계산
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            # NaN 값을 50으로 대체 (중립값)
            rsi = rsi.fillna(50)

            return rsi
        except Exception as e:
            self.logger.error(f"RSI 계산 중 오류: {str(e)}")
            return pd.Series([50] * len(prices), index=prices.index)

    def get_market_data_safely(self, ticker, timeframe='minute15', count=50, max_retries=3):
        """안전한 데이터 조회 함수"""
        for attempt in range(max_retries):
            try:
                self.logger.info(f"데이터 조회 시도 {attempt + 1}/{max_retries} - {ticker}, {timeframe}, {count}개")

                df = self.api.get_ohlcv_data(ticker, timeframe, count)

                if df is not None and len(df) >= 20:  # 최소한의 데이터 확인
                    self.logger.info(f"데이터 조회 성공: {len(df)}개 데이터")
                    return df
                else:
                    self.logger.warning(f"데이터 부족 또는 None: {len(df) if df is not None else 'None'}")

            except Exception as e:
                self.logger.error(f"데이터 조회 중 오류 (시도 {attempt + 1}): {str(e)}")

            # 재시도 전 잠시 대기
            if attempt < max_retries - 1:
                import time
                time.sleep(1)

        self.logger.error(f"모든 데이터 조회 시도 실패")
        return None

    def generate_signal(self, ticker, period=14, oversold=30, overbought=70, timeframe='minute15'):
        """RSI 기반 매매 신호 생성 - 개선된 버전

        Args:
            ticker (str): 티커 심볼
            period (int): RSI 계산 기간
            oversold (float): 과매도 기준값
            overbought (float): 과매수 기준값
            timeframe (str): 차트 시간대

        Returns:
            str: 'BUY', 'SELL', 'HOLD' 중 하나의 신호
        """
        try:
            # 매개변수 타입 검증 및 변환
            if isinstance(ticker, pd.Series):
                self.logger.error("ticker가 Series로 전달됨 - 잘못된 호출")
                return 'HOLD'

            # 숫자 매개변수들 검증 및 변환
            try:
                period = int(period) if not isinstance(period, pd.Series) else 14
                oversold = float(oversold) if not isinstance(oversold, pd.Series) else 30.0
                overbought = float(overbought) if not isinstance(overbought, pd.Series) else 70.0
            except (ValueError, TypeError) as e:
                self.logger.error(f"매개변수 변환 오류: {e}")
                period, oversold, overbought = 14, 30.0, 70.0

            # 매개변수 유효성 검사
            if period < 2:
                period = 14
            if oversold <= 0 or oversold >= 50:
                oversold = 30.0
            if overbought <= 50 or overbought >= 100:
                overbought = 70.0
            if oversold >= overbought:
                oversold, overbought = 30.0, 70.0

            self.logger.info(f"RSI 전략 시작 - {ticker}, 기간: {period}, 과매도: {oversold}, 과매수: {overbought}")

            # 안전한 데이터 조회 (충분한 여유를 두고 요청)
            required_count = max(period * 3, 60)  # 최소 60개 또는 period의 3배
            df = self.get_market_data_safely(ticker, timeframe, required_count)

            if df is None or len(df) < period + 5:
                self.logger.error(f"데이터 부족으로 RSI 계산 불가: {len(df) if df is not None else 'None'}개")
                return 'HOLD'

            # RSI 계산
            df['rsi'] = self.calculate_rsi(df['close'], period)

            # 최근 RSI 값들 확인
            if len(df) < 2:
                self.logger.error("RSI 신호 생성을 위한 데이터 부족")
                return 'HOLD'

            current_rsi = df['rsi'].iloc[-1]
            previous_rsi = df['rsi'].iloc[-2] if len(df) >= 2 else current_rsi

            # RSI 값 유효성 검사
            if pd.isna(current_rsi) or pd.isna(previous_rsi):
                self.logger.warning(f"RSI 값이 NaN: 현재={current_rsi}, 이전={previous_rsi}")
                return 'HOLD'

            self.logger.info(f"RSI 분석 - 현재: {current_rsi:.2f}, 이전: {previous_rsi:.2f}")

            # 현재가와 잔고 확인
            try:
                current_price = self.api.get_current_price(ticker)
                balance_coin = self.api.get_balance_coin(ticker)

                if current_price is None:
                    self.logger.error("현재가 조회 실패")
                    return 'HOLD'

            except Exception as e:
                self.logger.error(f"가격/잔고 조회 중 오류: {str(e)}")
                return 'HOLD'

            # 매도 조건 확인 (코인 보유 중)
            if balance_coin and balance_coin > 0:
                try:
                    avg_price = self.api.get_buy_avg(ticker)
                    if avg_price and avg_price > 0:
                        profit_loss = (current_price - avg_price) / avg_price * 100

                        self.logger.info(f"보유 상태 - 평균매수가: {avg_price:,.0f}, 현재가: {current_price:,.0f}, 수익률: {profit_loss:.2f}%")

                        # 과매수 구간에서 RSI 하락 시 매도
                        if current_rsi >= overbought and current_rsi < previous_rsi:
                            self.logger.info(f"과매수 하락 매도 신호 (RSI: {current_rsi:.2f}→{previous_rsi:.2f})")
                            return 'SELL'

                        # 수익 실현 (3% 이상)
                        if profit_loss >= 3.0:
                            self.logger.info(f"목표 수익률 달성 매도 (수익률: {profit_loss:.2f}%)")
                            return 'SELL'

                        # 손절 (-2% 이하)
                        if profit_loss <= -2.0:
                            self.logger.info(f"손절 매도 (손실률: {profit_loss:.2f}%)")
                            return 'SELL'

                        # RSI 80 이상에서 매도 (강한 과매수)
                        if current_rsi >= 80:
                            self.logger.info(f"강한 과매수 매도 (RSI: {current_rsi:.2f})")
                            return 'SELL'
                    else:
                        self.logger.warning("평균 매수가 조회 실패")

                except Exception as e:
                    self.logger.error(f"매도 조건 확인 중 오류: {str(e)}")

            # 매수 조건 확인 (코인 미보유)
            else:
                # 과매도에서 회복 신호
                if previous_rsi <= oversold and current_rsi > oversold:
                    # 추가 안전장치: 거래량 확인
                    try:
                        if len(df) >= 5:
                            recent_volumes = df['volume'].iloc[-5:]
                            avg_volume = recent_volumes.mean()
                            current_volume = df['volume'].iloc[-1]

                            if current_volume > avg_volume * 1.2:  # 20% 이상 거래량 증가
                                self.logger.info(f"과매도 회복 매수 신호 (RSI: {previous_rsi:.2f}→{current_rsi:.2f}, 거래량 증가)")
                                return 'BUY'
                            else:
                                self.logger.info(f"과매도 회복이나 거래량 부족 (현재량: {current_volume:.0f}, 평균: {avg_volume:.0f})")
                        else:
                            # 거래량 정보가 부족할 때는 RSI만으로 판단
                            self.logger.info(f"과매도 회복 매수 신호 (RSI: {previous_rsi:.2f}→{current_rsi:.2f})")
                            return 'BUY'
                    except Exception as e:
                        self.logger.error(f"거래량 분석 중 오류: {str(e)}")
                        # 거래량 분석 실패 시 RSI만으로 판단
                        self.logger.info(f"과매도 회복 매수 신호 (RSI: {previous_rsi:.2f}→{current_rsi:.2f})")
                        return 'BUY'

                # 강한 과매도에서 직접 매수 (RSI 20 이하)
                elif current_rsi <= 20:
                    self.logger.info(f"강한 과매도 매수 신호 (RSI: {current_rsi:.2f})")
                    return 'BUY'

            # 기본값: HOLD
            self.logger.info(f"RSI 홀드 신호 (RSI: {current_rsi:.2f})")
            return 'HOLD'

        except Exception as e:
            self.logger.error(f"RSI 전략 신호 생성 중 오류: {str(e)}")
            import traceback
            self.logger.error(f"오류 상세: {traceback.format_exc()}")
            return 'HOLD'