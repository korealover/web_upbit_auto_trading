"""
코인 수익성 분석 및 추천 시스템
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import time
from typing import List, Dict, Tuple, Optional


class CoinRecommender:
    """코인 수익성 분석 및 추천 클래스"""

    def __init__(self, upbit_api, logger=None):
        self.api = upbit_api
        self.logger = logger or logging.getLogger(__name__)
        # 캐시 추가
        self._market_cache = {}
        self._cache_timestamp = 0
        self._cache_duration = 300  # 5분 캐시
        # 거래량 티커 캐시 추가
        self._volume_tickers_cache = []
        self._volume_cache_timestamp = 0
        self._volume_cache_duration = 1800  # 30분 캐시

    def _get_top_volume_tickers(self, limit=50):
        """거래량 상위 티커들을 가져오는 메서드 - 최적화된 버전"""
        try:
            current_time = time.time()

            # 캐시 확인 (30분마다 갱신)
            if (self._volume_tickers_cache and
                    current_time - self._volume_cache_timestamp < self._volume_cache_duration):
                self.logger.info(f"캐시된 거래량 상위 {limit}개 티커 반환")
                return self._volume_tickers_cache[:limit]

            import pyupbit

            self.logger.info("거래량 상위 티커 조회 시작...")

            # 방법 1: pyupbit.get_market_ohlcv_from()를 사용해 한 번에 가져오기
            try:
                # 전체 시장 티커 조회ㅣ
                all_tickers = pyupbit.get_tickers(fiat="KRW")
                if not all_tickers:
                    self.logger.error("티커 목록을 가져올 수 없습니다.")
                    return self._get_fallback_tickers()

                self.logger.info(f"총 {len(all_tickers)}개 티커 발견")

                # 배치 단위로 처리하여 API 제한 회피
                ticker_volumes = []
                batch_size = 20  # 한 번에 20개씩 처리
                max_retries = 3

                for i in range(0, len(all_tickers), batch_size):
                    batch_tickers = all_tickers[i:i + batch_size]
                    batch_volumes = self._get_batch_ticker_volumes(batch_tickers, max_retries)
                    ticker_volumes.extend(batch_volumes)

                    # API 호출 간격 조절
                    if i + batch_size < len(all_tickers):
                        time.sleep(0.1)  # 100ms 대기

                # 거래량이 유효한 티커만 필터링
                valid_volumes = [(ticker, volume) for ticker, volume in ticker_volumes if volume > 0]

                if len(valid_volumes) < 10:
                    self.logger.warning(f"유효한 거래량 데이터가 부족함: {len(valid_volumes)}개")
                    return self._get_fallback_tickers()

                # 거래량 기준으로 정렬 (내림차순)
                valid_volumes.sort(key=lambda x: x[1], reverse=True)

                # 상위 티커들만 추출
                top_tickers = [ticker for ticker, volume in valid_volumes[:limit]]

                self.logger.info(f"거래량 기준 정렬 완료: 상위 {len(top_tickers)}개 선택")
                self.logger.info(f"상위 5개 티커: {top_tickers[:5]}")

                # 최소 개수 확보
                if len(top_tickers) < min(limit, 20):
                    self.logger.warning(f"충분한 티커를 확보하지 못함: {len(top_tickers)}개")
                    fallback_tickers = self._get_fallback_tickers()
                    for ticker in fallback_tickers:
                        if ticker not in top_tickers and len(top_tickers) < limit:
                            top_tickers.append(ticker)

                # 캐시 업데이트
                self._volume_tickers_cache = top_tickers
                self._volume_cache_timestamp = current_time

                self.logger.info(f"거래량 상위 {len(top_tickers)}개 티커 조회 성공")
                return top_tickers

            except Exception as api_error:
                self.logger.error(f"거래량 API 조회 실패: {api_error}")
                return self._get_fallback_tickers()

        except Exception as e:
            self.logger.error(f"거래량 상위 티커 조회 중 치명적 오류: {e}")
            return self._get_fallback_tickers()

    def _get_batch_ticker_volumes(self, tickers, max_retries=3):
        """배치 단위로 티커 거래량 조회"""
        import pyupbit
        volumes = []

        for ticker in tickers:
            retry_count = 0
            while retry_count < max_retries:
                try:
                    ticker_info = pyupbit.get_ticker(ticker)
                    if ticker_info and len(ticker_info) > 0:
                        volume_24h = ticker_info[0].get('acc_trade_price_24h', 0)
                        if volume_24h and volume_24h > 0:
                            volumes.append((ticker, float(volume_24h)))
                            self.logger.debug(f"{ticker}: {volume_24h:,.0f} KRW")
                        break
                    else:
                        volumes.append((ticker, 0))
                        break
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        self.logger.debug(f"{ticker} 거래량 조회 최종 실패: {e}")
                        volumes.append((ticker, 0))
                    else:
                        time.sleep(0.2)  # 재시도 전 대기

        return volumes

    def _get_fallback_tickers(self):
        """거래량 조회 실패 시 사용할 기본 주요 코인 목록 (2024-2025 최신 반영)"""
        return [
            # 메이저 코인 (거래량 상위)
            'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-ADA',
            'KRW-DOGE', 'KRW-AVAX', 'KRW-DOT', 'KRW-LINK', 'KRW-ATOM',

            # 한국 거래소 인기 코인
            'KRW-SHIB', 'KRW-MATIC', 'KRW-NEAR', 'KRW-FTM', 'KRW-ALGO',
            'KRW-MANA', 'KRW-SAND', 'KRW-AXS', 'KRW-CHZ', 'KRW-ENJ',

            # DeFi 관련
            'KRW-UNI', 'KRW-AAVE', 'KRW-CRV', 'KRW-COMP', 'KRW-MKR',
            'KRW-SNX', 'KRW-SUSHI', 'KRW-1INCH', 'KRW-BAL', 'KRW-YFI',

            # 레이어1/레이어2
            'KRW-FLOW', 'KRW-ICP', 'KRW-FIL', 'KRW-VET', 'KRW-EOS',
            'KRW-TRX', 'KRW-XTZ', 'KRW-KLAY', 'KRW-XLM', 'KRW-HBAR',

            # 기타 인기 코인
            'KRW-LTC', 'KRW-BCH', 'KRW-ETC', 'KRW-ZIL', 'KRW-THETA',
            'KRW-QTUM', 'KRW-OMG', 'KRW-BAT', 'KRW-ZRX', 'KRW-GRT'
        ]

    def get_market_analysis(self, timeframe='1h', period_hours=24) -> Dict:
        """전체 시장 분석 - 캐싱 및 성능 개선"""
        try:
            # 캐시 확인
            current_time = time.time()
            if (self._market_cache and
                    current_time - self._cache_timestamp < self._cache_duration):
                self.logger.info("캐시된 분석 결과 반환")
                return self._market_cache

            # pyupbit를 사용해서 전체 마켓 조회
            import pyupbit
            tickers = pyupbit.get_tickers(fiat="KRW")
            if not tickers:
                self.logger.error("마켓 정보를 가져올 수 없습니다.")
                return {}

            # 상위 거래량 코인 우선 분석으로 개수 제한
            try:
                # 거래량 상위 50개 코인을 가져오는 로직으로 변경
                major_tickers = self._get_top_volume_tickers(50)

                # 사용 가능한 티커만 필터링
                available_tickers = list(set(tickers))
                priority_tickers = [t for t in major_tickers if t in available_tickers]

                # 주요 코인 30개로 제한하여 성능 향상
                selected_tickers = priority_tickers[:30]
                krw_markets = [{'market': ticker} for ticker in selected_tickers]

                self.logger.info(f"총 {len(krw_markets)}개 주요 코인 분석 시작")

            except Exception as e:
                self.logger.warning(f"티커 정렬 중 오류, 기본 방식 사용: {e}")
                # 전체 티커 중 상위 30개만 사용
                krw_markets = [{'market': ticker} for ticker in tickers if ticker.startswith('KRW-')][:30]

            analysis_results = []
            failed_tickers = []
            success_count = 0

            # 병렬 처리를 위한 ThreadPoolExecutor 사용
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def analyze_single_coin(market):
                ticker = market['market']
                try:
                    analysis = self._analyze_coin_performance(ticker, timeframe, period_hours)
                    if analysis:
                        return analysis
                    else:
                        return None
                except Exception as e:
                    self.logger.debug(f"{ticker} 분석 중 오류: {e}")
                    return None

            # 스레드 풀로 병렬 처리 (최대 5개 스레드)
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 작업 제출
                future_to_market = {
                    executor.submit(analyze_single_coin, market): market
                    for market in krw_markets
                }

                # 결과 수집
                for future in as_completed(future_to_market, timeout=120):  # 2분 타임아웃
                    market = future_to_market[future]
                    ticker = market['market']

                    try:
                        result = future.result(timeout=10)  # 개별 작업 10초 타임아웃
                        if result:
                            analysis_results.append(result)
                            success_count += 1
                            self.logger.debug(f"{ticker} 분석 성공 ({success_count}/{len(krw_markets)})")
                        else:
                            failed_tickers.append(ticker)

                    except Exception as e:
                        self.logger.debug(f"{ticker} 분석 실패: {e}")
                        failed_tickers.append(ticker)

            # 결과 로깅
            self.logger.info(f"병렬 분석 완료: 성공 {success_count}개, 실패 {len(failed_tickers)}개")

            # 결과 캐시 저장
            result = {
                'total_analyzed': len(analysis_results),
                'results': sorted(analysis_results, key=lambda x: x['score'], reverse=True),
                'analysis_time': datetime.now().isoformat(),
                'failed_count': len(failed_tickers)
            }

            self._market_cache = result
            self._cache_timestamp = current_time

            return result

        except Exception as e:
            self.logger.error(f"시장 분석 중 치명적 오류: {e}")
            return self._market_cache if self._market_cache else {}

    def _analyze_coin_performance(self, ticker: str, timeframe: str, period_hours: int) -> Optional[Dict]:
        """개별 코인 성과 분석 - 타임아웃 및 재시도 최적화"""
        try:
            # 입력 유효성 검증
            if not ticker or not ticker.startswith('KRW-'):
                return None

            # 시간프레임에 따른 캔들 수 계산 (최소화)
            if timeframe == '1h':
                count = min(max(period_hours, 30), 50)  # 최대 50개로 제한
            elif timeframe == '1d':
                count = min(max(period_hours // 24, 7), 14)  # 최대 14개로 제한
            else:
                count = min(max(period_hours, 30), 50)

            # 데이터 가져오기 - 단일 시도로 변경 (성능 향상)
            try:
                df = self.api.get_ohlcv_data(ticker, 'minute60', count)
                current_price = self.api.get_current_price(ticker)
                ticker_info = self.api.get_ticker(ticker)

                # 빠른 실패 처리
                if (df is None or len(df) < 10 or
                    not current_price or current_price <= 0 or
                    not ticker_info):
                    return None

            except Exception:
                return None

            # 데이터 품질 검증 (간소화)
            if not self._validate_coin_data_fast(df, current_price, ticker_info):
                return None

            # 성과 지표 계산
            performance = self._calculate_performance_metrics(df, ticker_info)
            if not performance:
                return None

            # 기술적 분석 점수 (캐시된 계산 사용)
            technical_score = self._calculate_technical_score_fast(df)
            volume_score = self._calculate_volume_score_fast(df, ticker_info)
            volatility_score = self._calculate_volatility_score_fast(df)

            return_24h = max(-80, min(80, performance.get('return_24h', 0)))

            # 최종 점수 계산
            final_score = max(0, min(100, (
                return_24h * 0.3 +
                technical_score * 0.25 +
                volume_score * 0.25 +
                volatility_score * 0.2
            )))

            return {
                'ticker': ticker,
                'name': ticker.replace('KRW-', ''),
                'current_price': current_price,
                'score': round(final_score, 2),
                'performance': performance,
                'technical_score': round(technical_score, 2),
                'volume_score': round(volume_score, 2),
                'volatility_score': round(volatility_score, 2),
                'recommendation': self._get_recommendation(final_score),
                'risk_level': self._get_risk_level(volatility_score),
                'analysis_timestamp': datetime.now().isoformat()
            }

        except Exception:
            return None

    def _validate_coin_data_fast(self, df: pd.DataFrame, current_price: float, ticker_info: Dict) -> bool:
        """빠른 데이터 검증"""
        try:
            return (df is not None and len(df) >= 5 and
                   current_price > 0 and
                   ticker_info.get('acc_trade_volume_24h', 0) > 0)
        except:
            return False

    def _calculate_technical_score_fast(self, df: pd.DataFrame) -> float:
        """최적화된 기술적 분석"""
        try:
            scores = []
            prices = df['close']

            # RSI 간소화 (14 -> 7 기간으로 단축)
            try:
                delta = prices.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))

                if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]):
                    current_rsi = rsi.iloc[-1]
                    if 30 <= current_rsi <= 70:
                        scores.append(100 - abs(50 - current_rsi))
                    elif current_rsi < 30:
                        scores.append(80)
                    else:
                        scores.append(20)
            except:
                pass

            # 간소화된 이동평균 (5일, 10일로 단축)
            try:
                ma5 = prices.rolling(5).mean()
                ma10 = prices.rolling(10).mean()

                current_price = prices.iloc[-1]
                current_ma5 = ma5.iloc[-1]
                current_ma10 = ma10.iloc[-1]

                if current_price > current_ma5 > current_ma10:
                    scores.append(85)
                elif current_price > current_ma10:
                    scores.append(70)
                elif current_price < current_ma5 < current_ma10:
                    scores.append(25)
                else:
                    scores.append(50)
            except:
                scores.append(50)

            return np.mean(scores) if scores else 50

        except:
            return 50

    def _calculate_volume_score_fast(self, df: pd.DataFrame, ticker_info: Dict) -> float:
        """최적화된 거래량 분석"""
        try:
            recent_volumes = df['volume'].tail(3)  # 5 -> 3으로 단축
            avg_volume = df['volume'].mean()
            volume_ratio = recent_volumes.mean() / avg_volume if avg_volume > 0 else 1

            if volume_ratio > 2.0:
                return min(100, 90 + (10 if ticker_info.get('acc_trade_price_24h', 0) > 10000000000 else 0))
            elif volume_ratio > 1.5:
                return min(100, 75 + (5 if ticker_info.get('acc_trade_price_24h', 0) > 1000000000 else 0))
            elif volume_ratio > 1.2:
                return 60
            elif volume_ratio < 0.5:
                return 20
            else:
                return 50
        except:
            return 50

    def _calculate_volatility_score_fast(self, df: pd.DataFrame) -> float:
        """최적화된 변동성 분석"""
        try:
            price_changes = df['close'].pct_change().dropna()
            if len(price_changes) == 0:
                return 50

            volatility = price_changes.std()

            if 0.02 <= volatility <= 0.05:
                return 85
            elif 0.01 <= volatility <= 0.02:
                return 70
            elif 0.05 <= volatility <= 0.08:
                return 60
            elif volatility > 0.15:
                return 20
            elif volatility < 0.005:
                return 30
            else:
                return 50
        except:
            return 50

    def _calculate_performance_metrics(self, df: pd.DataFrame, ticker_info: Dict) -> Optional[Dict]:
        """성과 지표 계산 - 안전성 강화"""
        try:
            if len(df) < 2:
                return None

            # 수익률 계산
            current_price = df['close'].iloc[-1]
            price_1h = df['close'].iloc[-2] if len(df) > 1 else current_price
            price_4h = df['close'].iloc[-5] if len(df) > 4 else current_price
            price_24h = df['close'].iloc[0]

            # 0으로 나누기 방지
            def safe_return_calc(current, past):
                if past <= 0:
                    return 0
                return ((current - past) / past * 100)

            return {
                'return_1h': safe_return_calc(current_price, price_1h),
                'return_4h': safe_return_calc(current_price, price_4h),
                'return_24h': safe_return_calc(current_price, price_24h),
                'volume_24h': float(ticker_info.get('acc_trade_volume_24h', 0)),
                'trade_value_24h': float(ticker_info.get('acc_trade_price_24h', 0))
            }
        except Exception as e:
            self.logger.debug(f"성과 지표 계산 오류: {e}")
            return None

    def _calculate_technical_score(self, df: pd.DataFrame) -> float:
        """기술적 분석 점수 계산"""
        try:
            scores = []

            # RSI 계산 및 점수화
            rsi = self._calculate_rsi(df['close'])
            if len(rsi) > 0:
                current_rsi = rsi.iloc[-1]
                if 30 <= current_rsi <= 70:  # 정상 범위
                    rsi_score = 100 - abs(50 - current_rsi)  # 50에 가까울수록 높은 점수
                elif current_rsi < 30:  # 과매도
                    rsi_score = 80  # 매수 기회로 판단
                else:  # 과매수
                    rsi_score = 20  # 위험 신호
                scores.append(rsi_score)

            # 볼린저 밴드 분석
            bb_score = self._calculate_bollinger_score(df)
            scores.append(bb_score)

            # 이동평균 분석
            ma_score = self._calculate_ma_score(df)
            scores.append(ma_score)

            return np.mean(scores) if scores else 50

        except Exception as e:
            self.logger.error(f"기술적 분석 점수 계산 오류: {e}")
            return 50

    def _calculate_volume_score(self, df: pd.DataFrame, ticker_info: Dict) -> float:
        """거래량 분석 점수 계산"""
        try:
            # 최근 거래량 vs 평균 거래량
            recent_volumes = df['volume'].tail(5)
            avg_volume = df['volume'].mean()

            volume_ratio = recent_volumes.mean() / avg_volume if avg_volume > 0 else 1

            # 거래량 증가율에 따른 점수
            if volume_ratio > 2.0:  # 거래량 2배 이상 증가
                volume_score = 90
            elif volume_ratio > 1.5:  # 거래량 1.5배 이상 증가
                volume_score = 75
            elif volume_ratio > 1.2:  # 거래량 1.2배 이상 증가
                volume_score = 60
            elif volume_ratio < 0.5:  # 거래량 급감
                volume_score = 20
            else:
                volume_score = 50

            # 24시간 거래대금 고려
            trade_value = ticker_info.get('acc_trade_price_24h', 0)
            if trade_value > 10000000000:  # 100억 이상
                volume_score += 10
            elif trade_value > 1000000000:  # 10억 이상
                volume_score += 5

            return min(100, max(0, volume_score))

        except Exception as e:
            self.logger.error(f"거래량 분석 점수 계산 오류: {e}")
            return 50

    def _calculate_volatility_score(self, df: pd.DataFrame) -> float:
        """변동성 분석 점수 계산"""
        try:
            # 가격 변동률 계산
            price_changes = df['close'].pct_change().dropna()
            volatility = price_changes.std()

            # 적정 변동성 범위에서 높은 점수
            if 0.02 <= volatility <= 0.05:  # 2-5% 변동성
                volatility_score = 85
            elif 0.01 <= volatility <= 0.02:  # 1-2% 변동성
                volatility_score = 70
            elif 0.05 <= volatility <= 0.08:  # 5-8% 변동성
                volatility_score = 60
            elif volatility > 0.15:  # 15% 이상 고변동성
                volatility_score = 20
            elif volatility < 0.005:  # 0.5% 미만 저변동성
                volatility_score = 30
            else:
                volatility_score = 50

            return volatility_score

        except Exception as e:
            self.logger.error(f"변동성 분석 점수 계산 오류: {e}")
            return 50

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """RSI 계산"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except Exception:
            return pd.Series()

    def _calculate_bollinger_score(self, df: pd.DataFrame) -> float:
        """볼린저 밴드 분석 점수"""
        try:
            prices = df['close']
            ma20 = prices.rolling(20).mean()
            std20 = prices.rolling(20).std()
            upper = ma20 + (std20 * 2)
            lower = ma20 - (std20 * 2)

            current_price = prices.iloc[-1]
            current_upper = upper.iloc[-1]
            current_lower = lower.iloc[-1]
            current_ma = ma20.iloc[-1]

            # 볼린저 밴드 위치에 따른 점수
            if pd.isna(current_upper) or pd.isna(current_lower):
                return 50

            position = (current_price - current_lower) / (current_upper - current_lower)

            if 0.2 <= position <= 0.8:  # 밴드 중앙 부근
                return 80
            elif position < 0.2:  # 하단 밴드 근처 (매수 기회)
                return 75
            else:  # 상단 밴드 근처 (주의)
                return 40

        except Exception as e:
            self.logger.error(f"볼린저 밴드 점수 계산 오류: {e}")
            return 50

    def _calculate_ma_score(self, df: pd.DataFrame) -> float:
        """이동평균 분석 점수"""
        try:
            prices = df['close']
            ma5 = prices.rolling(5).mean()
            ma20 = prices.rolling(20).mean()

            current_price = prices.iloc[-1]
            current_ma5 = ma5.iloc[-1]
            current_ma20 = ma20.iloc[-1]

            score = 50

            # 현재가 > 단기 이평 > 장기 이평 (상승 추세)
            if current_price > current_ma5 > current_ma20:
                score = 85
            # 현재가 > 장기 이평 (기본 상승)
            elif current_price > current_ma20:
                score = 70
            # 현재가 < 단기 이평 < 장기 이평 (하락 추세)
            elif current_price < current_ma5 < current_ma20:
                score = 25
            # 현재가 < 장기 이평 (기본 하락)
            elif current_price < current_ma20:
                score = 35

            return score

        except Exception as e:
            self.logger.error(f"이동평균 점수 계산 오류: {e}")
            return 50

    def _get_recommendation(self, score: float) -> str:
        """점수에 따른 추천 등급"""
        if score >= 80:
            return "강력매수"
        elif score >= 70:
            return "매수"
        elif score >= 60:
            return "약간매수"
        elif score >= 40:
            return "보유"
        elif score >= 30:
            return "약간매도"
        else:
            return "매도"

    def _get_risk_level(self, volatility_score: float) -> str:
        """변동성 점수에 따른 위험도"""
        if volatility_score >= 70:
            return "낮음"
        elif volatility_score >= 50:
            return "보통"
        elif volatility_score >= 30:
            return "높음"
        else:
            return "매우높음"

    def get_top_recommendations(self, limit: int = 10, min_score: float = 30) -> List[Dict]:
        """상위 추천 코인 목록"""
        try:
            analysis = self.get_market_analysis()
            if not analysis or 'results' not in analysis:
                return []

            # 최소 점수 이상의 코인만 필터링
            filtered_results = [
                coin for coin in analysis['results']
                if coin['score'] >= min_score
            ]

            return filtered_results[:limit]

        except Exception as e:
            self.logger.error(f"상위 추천 코인 조회 오류: {e}")
            return []

    def get_coin_detailed_analysis(self, ticker: str) -> Dict:
        """특정 코인 상세 분석"""
        try:
            self.logger.info(f"{ticker} 상세 분석 시작")

            # 기본 분석 수행
            analysis = self._analyze_coin_performance(ticker, '1h', 24)
            if not analysis:
                self.logger.warning(f"{ticker} 기본 분석 실패 - 데이터 없음")
                return {}

            self.logger.info(f"{ticker} 기본 분석 완료: 점수={analysis.get('score', 'N/A')}")

            # 추가 상세 정보
            try:
                df = self.api.get_ohlcv_data(ticker, 'minute60', 168)  # 1주일 데이터
                if df is not None and len(df) > 0:
                    self.logger.debug(f"{ticker} 1주일 데이터 획득: {len(df)}개 캔들")

                    # 주간 성과
                    week_return = ((df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100) if len(df) > 0 else 0
                    analysis['performance']['return_1w'] = week_return

                    # 주간 최고/최저
                    analysis['performance']['week_high'] = float(df['high'].max())
                    analysis['performance']['week_low'] = float(df['low'].min())

                    # 평균 거래량
                    analysis['performance']['avg_volume_1w'] = float(df['volume'].mean())

                    self.logger.debug(f"{ticker} 주간 데이터 추가 완료")
                else:
                    self.logger.warning(f"{ticker} 1주일 데이터 없음")
            except Exception as week_error:
                self.logger.warning(f"{ticker} 주간 데이터 처리 오류: {week_error}")

            self.logger.info(f"{ticker} 상세 분석 완료")
            return analysis

        except Exception as e:
            self.logger.error(f"{ticker} 상세 분석 중 치명적 오류: {str(e)}", exc_info=True)
            return {}