import pandas as pd


class RSIStrategy:
    """RSI 지표 기반 트레이딩 전략"""

    def __init__(self, upbit_api, logger):
        """초기화"""
        self.api = upbit_api
        self.logger = logger

    def calculate_rsi(self, prices, period=14, use_ema=True):
        """RSI 계산 - 개선된 버전 (SMA/EMA 선택 가능)"""
        global rsi
        try:
            if len(prices) < period + 1:
                self.logger.warning(f"RSI 계산을 위한 데이터 부족: {len(prices)}개 (최소 {period + 1}개 필요)")
                return pd.Series([50] * len(prices), index=prices.index)

            delta = prices.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)

            if use_ema:
                try:
                    # 지수 이동평균 방식 (표준 RSI)
                    alpha = 1.0 / period

                    # 첫 번째 기간은 단순 평균 (인덱스 안전 처리)
                    if len(gain) > period:
                        first_avg_gain = gain.iloc[1:period + 1].mean()
                        first_avg_loss = loss.iloc[1:period + 1].mean()
                    else:
                        # 데이터 부족 시 사용 가능한 데이터로 계산
                        first_avg_gain = gain.iloc[1:].mean()
                        first_avg_loss = loss.iloc[1:].mean()

                    avg_gains = [first_avg_gain]
                    avg_losses = [first_avg_loss]

                    for i in range(period + 1, len(prices)):
                        if i < len(gain):  # 인덱스 범위 확인
                            avg_gain = alpha * gain.iloc[i] + (1 - alpha) * avg_gains[-1]
                            avg_loss = alpha * loss.iloc[i] + (1 - alpha) * avg_losses[-1]
                            avg_gains.append(avg_gain)
                            avg_losses.append(avg_loss)

                    # RSI 계산
                    rsi_values = []
                    for i in range(len(avg_gains)):
                        if avg_losses[i] == 0:
                            rsi_values.append(100.0)
                        else:
                            rs = avg_gains[i] / avg_losses[i]
                            rsi_values.append(100 - (100 / (1 + rs)))

                    # 전체 길이에 맞춰 RSI 시리즈 생성
                    full_rsi = pd.Series([50] * len(prices), index=prices.index)
                    if len(rsi_values) > 0:
                        start_idx = min(period, len(prices) - len(rsi_values))
                        end_idx = start_idx + len(rsi_values)
                        full_rsi.iloc[start_idx:end_idx] = rsi_values
                    rsi = full_rsi.fillna(50)

                except Exception as ema_error:
                    self.logger.warning(f"EMA RSI 계산 실패, SMA로 대체: {str(ema_error)}")
                    # EMA 계산 실패 시 SMA로 대체
                    use_ema = False

            if not use_ema:
                # 기존 단순 이동평균 방식
                avg_gain = gain.rolling(window=period).mean()
                avg_loss = loss.rolling(window=period).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
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

    def generate_signal(self, ticker, period=14, oversold=30, overbought=70, timeframe='minute15', use_multi_timeframe=False, use_divergence=True):
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

            # 기본 RSI 계산
            required_count = max(period * 3, 60)
            df = self.get_market_data_safely(ticker, timeframe, required_count)

            if df is None or len(df) < period + 5:
                self.logger.error(f"데이터 부족으로 RSI 계산 불가")
                return 'HOLD'

            # RSI 계산 (지수 이동평균 사용)
            df['rsi'] = self.calculate_rsi(df['close'], period, use_ema=True)

            current_rsi = df['rsi'].iloc[-1]
            previous_rsi = df['rsi'].iloc[-2] if len(df) >= 2 else current_rsi

            # 다중 시간대 분석 (선택적)
            timeframe_alignment = 'NEUTRAL'
            if use_multi_timeframe:
                multi_rsi = self.get_multi_timeframe_rsi(ticker)
                timeframe_alignment = self.check_timeframe_alignment(multi_rsi)

            # 다이버전스 확인 (선택적)
            divergence = None
            if use_divergence:
                divergence = self.check_divergence(df['close'], df['rsi'])

            # RSI 트렌드 확인
            rsi_trend = self.check_rsi_trend(df['rsi'])

            # 현재가와 잔고 확인
            current_price = self.api.get_current_price(ticker)
            balance_coin = self.api.get_balance_coin(ticker)

            if current_price is None:
                self.logger.error(f"현재가 조회 실패: {ticker}")
                return 'HOLD'

            self.logger.info(f"RSI 분석 - 현재: {current_rsi:.2f}, 트렌드: {rsi_trend}, 다이버전스: {divergence}")

            # 매도 조건 (코인 보유 중)
            if balance_coin and balance_coin > 0:
                try:
                    avg_price = self.api.get_buy_avg(ticker)
                    if avg_price and avg_price > 0:
                        profit_loss = (current_price - avg_price) / avg_price * 100

                        # 1. 기존 매도 조건들
                        if (overbought <= current_rsi < previous_rsi) or \
                                profit_loss >= 3.0 or profit_loss <= -2.0 or current_rsi >= 80:
                            return 'SELL'

                        # 2. 다이버전스 기반 매도
                        if divergence == 'BEARISH' and current_rsi > 50:
                            self.logger.info("Bearish Divergence 매도 신호")
                            return 'SELL'

                        # 3. 다중 시간대 과매수 정렬
                        if timeframe_alignment == 'OVERBOUGHT_ALIGNED':
                            self.logger.info("다중 시간대 과매수 매도 신호")
                            return 'SELL'

                except Exception as e:
                    self.logger.error(f"매도 조건 확인 중 오류: {str(e)}")

            # 매수 조건 (코인 미보유)
            else:
                # 거래량 확인
                volume_confirmed = self.check_volume_confirmation(df)

                # 1. 기존 과매도 회복 조건
                if previous_rsi <= oversold < current_rsi:
                    if volume_confirmed:
                        self.logger.info(f"과매도 회복 매수 신호 (거래량 확인됨)")
                        return 'BUY'
                    else:
                        self.logger.info(f"과매도 회복이나 거래량 부족")
                        return 'HOLD'

                # 2. 강한 과매도에서 상승 전환
                elif current_rsi <= 20 and rsi_trend == 'RISING':
                    self.logger.info("강한 과매도 상승 전환 매수 신호")
                    return 'BUY'

                # 3. 다이버전스 기반 매수
                elif divergence == 'BULLISH' and current_rsi < 50:
                    if volume_confirmed:
                        self.logger.info("Bullish Divergence 매수 신호 (거래량 확인됨)")
                        return 'BUY'
                    else:
                        self.logger.info("Bullish Divergence 감지되나 거래량 부족")
                        return 'HOLD'

                # 4. 다중 시간대 과매도 정렬
                elif timeframe_alignment == 'OVERSOLD_ALIGNED':
                    self.logger.info("다중 시간대 과매도 매수 신호")
                    return 'BUY'

            return 'HOLD'

        except Exception as e:
            self.logger.error(f"RSI 전략 신호 생성 중 오류: {str(e)}")
            import traceback
            self.logger.error(f"오류 상세: {traceback.format_exc()}")
            return 'HOLD'

    def check_rsi_trend(self, rsi_values, period=3):
        """RSI 트렌드 확인 (상승/하락/횡보)"""
        try:
            if len(rsi_values) < period:
                return 'NEUTRAL'

            recent_rsi = rsi_values.iloc[-period:]

            # 연속 상승
            if all(recent_rsi.iloc[i] > recent_rsi.iloc[i - 1] for i in range(1, len(recent_rsi))):
                return 'RISING'

            # 연속 하락
            if all(recent_rsi.iloc[i] < recent_rsi.iloc[i - 1] for i in range(1, len(recent_rsi))):
                return 'FALLING'

            return 'NEUTRAL'

        except Exception as e:
            self.logger.error(f"RSI 트렌드 확인 중 오류: {str(e)}")
            return 'NEUTRAL'

    def get_multi_timeframe_rsi(self, ticker, timeframes=None, period=14):
        """다중 시간대 RSI 확인"""
        if timeframes is None:
            timeframes = ['minute15', 'minute60', 'day']
        multi_rsi = {}

        for tf in timeframes:
            try:
                df = self.get_market_data_safely(ticker, tf, max(period * 3, 60))
                if df is not None and len(df) >= period + 5:
                    rsi = self.calculate_rsi(df['close'], period)
                    current_rsi = rsi.iloc[-1]
                    multi_rsi[tf] = {
                        'rsi': current_rsi,
                        'trend': self.check_rsi_trend(rsi)
                    }
                    self.logger.info(f"{tf} RSI: {current_rsi:.2f} ({multi_rsi[tf]['trend']})")
                else:
                    self.logger.warning(f"{tf} 데이터 부족")

            except Exception as e:
                self.logger.error(f"{tf} RSI 계산 중 오류: {str(e)}")

        return multi_rsi

    def check_timeframe_alignment(self, multi_rsi):
        """시간대별 RSI 정렬 확인"""
        try:
            if len(multi_rsi) < 2:
                return 'NEUTRAL'

            # 모든 시간대가 과매도 상태
            oversold_count = sum(1 for data in multi_rsi.values() if data['rsi'] <= 30)
            overbought_count = sum(1 for data in multi_rsi.values() if data['rsi'] >= 70)

            total_timeframes = len(multi_rsi)

            if oversold_count >= total_timeframes * 0.7:  # 70% 이상
                return 'OVERSOLD_ALIGNED'
            elif overbought_count >= total_timeframes * 0.7:
                return 'OVERBOUGHT_ALIGNED'

            return 'NEUTRAL'

        except Exception as e:
            self.logger.error(f"시간대 정렬 확인 중 오류: {str(e)}")
            return 'NEUTRAL'

    def check_divergence(self, prices, rsi_values, lookback=10):
        """RSI 다이버전스 확인 - 개선된 버전"""
        try:
            if len(prices) < lookback or len(rsi_values) < lookback:
                return None

            recent_prices = prices.iloc[-lookback:]
            recent_rsi = rsi_values.iloc[-lookback:]

            # 중간 지점과 현재 지점 비교로 다이버전스 확인
            mid_point = lookback // 2

            # 가격과 RSI의 변화 방향 계산
            price_change = recent_prices.iloc[-1] - recent_prices.iloc[mid_point]
            rsi_change = recent_rsi.iloc[-1] - recent_rsi.iloc[mid_point]

            # 가격 변화율과 RSI 변화율 계산
            price_change_pct = price_change / recent_prices.iloc[mid_point] * 100
            rsi_change_pct = rsi_change / recent_rsi.iloc[mid_point] * 100

            # 임계값 설정 (변화가 미미하면 다이버전스로 판단하지 않음)
            min_change_threshold = 2.0  # 2% 이상 변화 시에만 고려

            if abs(price_change_pct) < min_change_threshold:
                return None

            # Bearish Divergence: 가격은 상승, RSI는 하락
            if price_change > 0 and rsi_change < 0 and abs(rsi_change_pct) > min_change_threshold:
                self.logger.info(f"Bearish Divergence 감지 - 가격변화: {price_change_pct:.2f}%, RSI변화: {rsi_change_pct:.2f}%")
                return 'BEARISH'

            # Bullish Divergence: 가격은 하락, RSI는 상승
            if price_change < 0 and rsi_change > 0 and abs(rsi_change_pct) > min_change_threshold:
                self.logger.info(f"Bullish Divergence 감지 - 가격변화: {price_change_pct:.2f}%, RSI변화: {rsi_change_pct:.2f}%")
                return 'BULLISH'

            return None

        except Exception as e:
            self.logger.error(f"다이버전스 확인 중 오류: {str(e)}")
            return None

    def check_volume_confirmation(self, df, lookback=5):
        """거래량 확인을 통한 신호 검증"""
        try:
            if len(df) < lookback:
                return True  # 데이터 부족 시 기본 승인

            recent_volumes = df['volume'].iloc[-lookback:]
            avg_volume = recent_volumes.mean()
            current_volume = df['volume'].iloc[-1]

            # 현재 거래량이 평균의 120% 이상이면 승인
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            self.logger.info(f"거래량 분석 - 현재: {current_volume:.0f}, 평균: {avg_volume:.0f}, 비율: {volume_ratio:.2f}")

            return volume_ratio >= 1.2

        except Exception as e:
            self.logger.error(f"거래량 확인 중 오류: {str(e)}")
            return True