"""
코인 수익성 분석 및 추천 시스템
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Tuple, Optional


class CoinRecommender:
    """코인 수익성 분석 및 추천 클래스"""

    def __init__(self, upbit_api, logger=None):
        self.api = upbit_api
        self.logger = logger or logging.getLogger(__name__)

    def get_market_analysis(self, timeframe='1h', period_hours=24) -> Dict:
        """전체 시장 분석"""
        try:
            # pyupbit를 사용해서 전체 마켓 조회
            import pyupbit
            tickers = pyupbit.get_tickers(fiat="KRW")
            if not tickers:
                self.logger.error("마켓 정보를 가져올 수 없습니다.")
                return {}

            # KRW 마켓만 필터링 (이미 KRW만 가져왔지만 안전을 위해)
            krw_markets = [{'market': ticker} for ticker in tickers if ticker.startswith('KRW-')]

            analysis_results = []
            failed_tickers = []

            for market in krw_markets[:50]:  # 처리 시간을 위해 상위 50개만 분석
                ticker = market['market']
                try:
                    analysis = self._analyze_coin_performance(ticker, timeframe, period_hours)
                    if analysis:
                        analysis_results.append(analysis)
                    else:
                        failed_tickers.append(ticker)
                except Exception as e:
                    self.logger.warning(f"{ticker} 분석 중 오류: {e}")
                    failed_tickers.append(ticker)
                    continue

            # 실패한 티커들에 대한 로깅
            if failed_tickers:
                self.logger.info(f"분석 실패한 {len(failed_tickers)}개 티커: {failed_tickers[:10]}{'...' if len(failed_tickers) > 10 else ''}")

            return {
                'total_analyzed': len(analysis_results),
                'results': sorted(analysis_results, key=lambda x: x['score'], reverse=True),
                'analysis_time': datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.error(f"시장 분석 중 오류: {e}")
            return {}

    def _analyze_coin_performance(self, ticker: str, timeframe: str, period_hours: int) -> Optional[Dict]:
        """개별 코인 성과 분석"""
        try:
            # 시간프레임에 따른 캔들 수 계산
            if timeframe == '1h':
                count = period_hours
            elif timeframe == '1d':
                count = period_hours // 24
            elif timeframe == '4h':
                count = period_hours // 4
            else:
                count = period_hours

            # OHLCV 데이터 가져오기
            df = self.api.get_ohlcv_data(ticker, f'minute60', count)
            if df is None or len(df) < 10:
                return None

            # 현재가 정보
            current_price = self.api.get_current_price(ticker)
            if not current_price:
                return None

            # 24시간 거래량 정보
            ticker_info = self.api.get_ticker(ticker)
            if not ticker_info:
                return None

            # 성과 지표 계산
            performance = self._calculate_performance_metrics(df, ticker_info)

            # 기술적 분석 점수
            technical_score = self._calculate_technical_score(df)

            # 거래량 분석 점수
            volume_score = self._calculate_volume_score(df, ticker_info)

            # 변동성 점수
            volatility_score = self._calculate_volatility_score(df)

            # 점수 유효성 검증
            return_24h = performance.get('return_24h', 0) if performance else 0

            # 극단적인 수익률 제한 (-50% ~ +50%)
            return_24h = max(-50, min(50, return_24h))

            # 최종 점수 계산 (가중평균)
            final_score = (
                return_24h * 0.3 +                 # 24시간 수익률 30%
                technical_score * 0.25 +           # 기술적 분석 25%
                volume_score * 0.25 +              # 거래량 분석 25%
                volatility_score * 0.2             # 변동성 분석 20%
            )

            # 점수 범위 제한 (0-100)
            final_score = max(0, min(100, final_score))

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

        except Exception as e:
            self.logger.error(f"{ticker} 성과 분석 중 오류: {e}")
            return None

    def _calculate_performance_metrics(self, df: pd.DataFrame, ticker_info: Dict) -> Dict:
        """성과 지표 계산"""
        try:
            # 수익률 계산
            current_price = df['close'].iloc[-1]
            price_1h = df['close'].iloc[-2] if len(df) > 1 else current_price
            price_4h = df['close'].iloc[-5] if len(df) > 4 else current_price
            price_24h = df['close'].iloc[0]

            return {
                'return_1h': ((current_price - price_1h) / price_1h * 100) if price_1h > 0 else 0,
                'return_4h': ((current_price - price_4h) / price_4h * 100) if price_4h > 0 else 0,
                'return_24h': ((current_price - price_24h) / price_24h * 100) if price_24h > 0 else 0,
                'volume_24h': ticker_info.get('acc_trade_volume_24h', 0),
                'trade_value_24h': ticker_info.get('acc_trade_price_24h', 0)
            }
        except Exception as e:
            self.logger.error(f"성과 지표 계산 오류: {e}")
            return {}

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

    def get_top_recommendations(self, limit: int = 10, min_score: float = 60) -> List[Dict]:
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
            analysis = self._analyze_coin_performance(ticker, '1h', 24)
            if not analysis:
                return {}

            # 추가 상세 정보
            df = self.api.get_ohlcv_data(ticker, 'minute60', 168)  # 1주일 데이터
            if df is not None and len(df) > 0:
                # 주간 성과
                week_return = ((df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100) if len(df) > 0 else 0
                analysis['performance']['return_1w'] = week_return

                # 주간 최고/최저
                analysis['performance']['week_high'] = df['high'].max()
                analysis['performance']['week_low'] = df['low'].min()

                # 평균 거래량
                analysis['performance']['avg_volume_1w'] = df['volume'].mean()

            return analysis

        except Exception as e:
            self.logger.error(f"{ticker} 상세 분석 오류: {e}")
            return {}