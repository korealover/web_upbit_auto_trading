import time
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import platform
from datetime import datetime, timedelta
import asyncio
import pyupbit
import logging
from config import Config
from logging.handlers import TimedRotatingFileHandler
import aiohttp
import json
import sys
from io import BytesIO


# matplotlib 한글 폰트 설정
def setup_korean_font():
    """한글 폰트 설정"""
    try:
        system = platform.system()

        if system == 'Windows':
            # Windows의 경우 맑은 고딕 사용
            font_candidates = ['Malgun Gothic', 'Microsoft YaHei', 'SimHei']
        elif system == 'Darwin':  # macOS
            # macOS의 경우 애플고딕 사용
            font_candidates = ['AppleGothic', 'Apple SD Gothic Neo', 'Helvetica']
        else:  # Linux
            # Linux의 경우 나눔고딕 사용
            font_candidates = ['NanumGothic', 'Nanum Gothic', 'DejaVu Sans']

        # 시스템에서 사용 가능한 폰트 찾기
        available_fonts = [f.name for f in fm.fontManager.ttflist]

        # 한글 폰트 후보 중에서 사용 가능한 것 찾기
        for font in font_candidates:
            if font in available_fonts:
                plt.rcParams['font.family'] = font
                plt.rcParams['axes.unicode_minus'] = False
                print(f"한글 폰트 설정 완료: {font}")
                return

        # 한글 폰트를 찾지 못한 경우 기본 설정
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False
        print("한글 폰트를 찾지 못했습니다. 기본 폰트를 사용합니다.")

    except Exception as e:
        print(f"폰트 설정 중 오류 발생: {str(e)}")
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False


# 한글 폰트 설정 실행
setup_korean_font()

# 로깅 설정
os.makedirs("logs", exist_ok=True)


def setup_logger():
    """일별 로그 파일 자동 생성을 위한 로깅 설정"""
    logger = logging.getLogger('volume_analyzer')
    logger.setLevel(logging.INFO)

    # 이미 핸들러가 있다면 모두 제거
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 파일 핸들러
    log_file = os.path.join("logs", "volume_analyzer.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.suffix = "%Y%m%d"

    # 포맷 설정
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # 핸들러 추가
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# 로거 초기화
logger = setup_logger()


class TelegramBot:
    """텔레그램 봇 클래스"""

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = None

    async def get_session(self):
        """HTTP 세션 관리"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def send_message(self, text, parse_mode='Markdown'):
        """텔레그램 메시지 전송"""
        try:
            session = await self.get_session()
            url = f"{self.base_url}/sendMessage"

            data = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': parse_mode
            }

            async with session.post(url, data=data) as response:
                if response.status == 200:
                    logger.info("텔레그램 메시지 전송 성공")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"텔레그램 메시지 전송 실패: {response.status} - {error_text}")
                    return False

        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 중 오류: {str(e)}")
            return False

    async def send_photo(self, photo_bytes, caption=None):
        """텔레그램 이미지 전송"""
        try:
            session = await self.get_session()
            url = f"{self.base_url}/sendPhoto"

            data = aiohttp.FormData()
            data.add_field('chat_id', str(self.chat_id))
            data.add_field('photo', photo_bytes, filename='volume_chart.png', content_type='image/png')

            if caption:
                data.add_field('caption', caption)

            async with session.post(url, data=data) as response:
                if response.status == 200:
                    logger.info("텔레그램 이미지 전송 성공")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"텔레그램 이미지 전송 실패: {response.status} - {error_text}")
                    return False

        except Exception as e:
            logger.error(f"텔레그램 이미지 전송 중 오류: {str(e)}")
            return False

    async def close(self):
        """세션 정리"""
        if self.session and not self.session.closed:
            await self.session.close()


class VolumeAnalyzer:
    """거래량 분석 클래스"""

    def __init__(self):
        self.telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

    async def get_all_krw_tickers(self):
        """모든 KRW 마켓 티커 조회"""
        try:
            tickers = pyupbit.get_tickers(fiat="KRW")
            logger.info(f"총 {len(tickers)}개의 KRW 마켓 코인 조회 완료")
            return tickers
        except Exception as e:
            logger.error(f"티커 조회 실패: {str(e)}")
            return []

    async def get_volume_data(self, ticker):
        """개별 코인의 거래량 데이터 조회"""
        try:
            # 24시간 OHLCV 데이터 조회
            ohlcv_1d = pyupbit.get_ohlcv(ticker, interval="day", count=2)
            # 1시간 OHLCV 데이터 조회 (최근 24시간)
            ohlcv_1h = pyupbit.get_ohlcv(ticker, interval="minute60", count=24)

            if ohlcv_1d is None or len(ohlcv_1d) == 0:
                return None

            # 현재가 조회
            current_price = pyupbit.get_current_price(ticker)
            if current_price is None:
                return None

            # 24시간 거래량 및 거래대금 계산
            volume_24h = ohlcv_1d.iloc[-1]['volume']
            volume_krw_24h = volume_24h * current_price

            # 전일 대비 거래량 변화율 계산
            if len(ohlcv_1d) > 1:
                prev_volume = ohlcv_1d.iloc[-2]['volume']
                volume_change_rate = ((volume_24h - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0
            else:
                volume_change_rate = 0

            # 24시간 가격 변동률 계산
            if len(ohlcv_1d) > 1:
                prev_close = ohlcv_1d.iloc[-2]['close']
                price_change_rate = ((current_price - prev_close) / prev_close * 100)
            else:
                price_change_rate = 0

            # 최근 1시간 거래량 (급등 감지용)
            recent_volume_1h = 0
            if ohlcv_1h is not None and len(ohlcv_1h) > 0:
                recent_volume_1h = ohlcv_1h.iloc[-1]['volume']

            # 평균 시간당 거래량 대비 최근 1시간 거래량 비율
            avg_hourly_volume = volume_24h / 24
            volume_spike_ratio = (recent_volume_1h / avg_hourly_volume) if avg_hourly_volume > 0 else 0

            return {
                'ticker': ticker,
                'current_price': current_price,
                'volume_24h': volume_24h,
                'volume_krw_24h': volume_krw_24h,
                'volume_change_rate': volume_change_rate,
                'price_change_rate': price_change_rate,
                'recent_volume_1h': recent_volume_1h,
                'volume_spike_ratio': volume_spike_ratio
            }

        except Exception as e:
            logger.warning(f"{ticker} 거래량 데이터 조회 실패: {str(e)}")
            return None

    async def analyze_top_volume_coins(self, top_n=5):
        """거래량 상위 코인 분석"""
        logger.info("거래량 상위 코인 분석 시작...")

        # 모든 KRW 마켓 티커 조회
        tickers = await self.get_all_krw_tickers()
        if not tickers:
            logger.error("티커 조회 실패")
            return []

        volume_data = []

        # 각 코인의 거래량 데이터 수집
        for i, ticker in enumerate(tickers):
            if i % 10 == 0:
                logger.info(f"진행률: {i}/{len(tickers)} ({i / len(tickers) * 100:.1f}%)")

            data = await self.get_volume_data(ticker)
            if data:
                volume_data.append(data)

            # API 호출 제한 고려
            await asyncio.sleep(0.1)

        # 거래대금 기준으로 정렬
        volume_data.sort(key=lambda x: x['volume_krw_24h'], reverse=True)

        logger.info(f"총 {len(volume_data)}개 코인의 거래량 데이터 수집 완료")

        # 상위 N개 반환
        return volume_data[:top_n]

    def create_volume_chart(self, top_coins):
        """거래량 상위 코인 차트 생성"""
        try:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

            # 코인명 및 데이터 추출
            coin_names = [coin['ticker'].split('-')[1] for coin in top_coins]
            volumes_krw = [coin['volume_krw_24h'] / 1e8 for coin in top_coins]  # 억원 단위
            volume_changes = [coin['volume_change_rate'] for coin in top_coins]
            price_changes = [coin['price_change_rate'] for coin in top_coins]

            # 1. 거래대금 차트
            bars1 = ax1.bar(coin_names, volumes_krw, color='skyblue', alpha=0.7)
            ax1.set_title('거래량 상위 5개 코인 - 24시간 거래대금', fontsize=14, fontweight='bold')
            ax1.set_ylabel('거래대금 (억원)', fontsize=12)
            ax1.grid(axis='y', alpha=0.3)

            # 거래대금 값 표시
            for bar, volume in zip(bars1, volumes_krw):
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width() / 2., height + height * 0.01,
                         f'{volume:.0f}억', ha='center', va='bottom', fontsize=10)

            # 2. 변동률 차트
            colors = ['red' if change > 0 else 'blue' for change in price_changes]
            bars2 = ax2.bar(coin_names, price_changes, color=colors, alpha=0.7)
            ax2.set_title('24시간 가격 변동률', fontsize=14, fontweight='bold')
            ax2.set_ylabel('변동률 (%)', fontsize=12)
            ax2.set_xlabel('코인', fontsize=12)
            ax2.grid(axis='y', alpha=0.3)
            ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

            # 변동률 값 표시
            for bar, change in zip(bars2, price_changes):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width() / 2.,
                         height + (1 if height > 0 else -3),
                         f'{change:+.1f}%', ha='center',
                         va='bottom' if height > 0 else 'top', fontsize=10)

            plt.tight_layout()

            # 바이트로 변환
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            img_buffer.seek(0)
            plt.close()

            return img_buffer.getvalue()

        except Exception as e:
            logger.error(f"차트 생성 실패: {str(e)}")
            plt.close()
            return None

    async def send_volume_report(self, top_coins):
        """거래량 상위 코인 보고서 전송"""
        try:
            # 보고서 메시지 생성
            report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            message = f"""📊 *거래량 상위 5개 코인 분석 보고서*
📅 {report_time}

"""

            for i, coin in enumerate(top_coins, 1):
                coin_name = coin['ticker'].split('-')[1]
                volume_krw_formatted = f"{coin['volume_krw_24h'] / 1e8:.1f}억원"

                # 거래량 변화 이모지
                volume_emoji = "📈" if coin['volume_change_rate'] > 0 else "📉" if coin['volume_change_rate'] < 0 else "➡️"

                # 가격 변화 이모지
                price_emoji = "🔴" if coin['price_change_rate'] > 0 else "🔵" if coin['price_change_rate'] < 0 else "⚪"

                # 급등 여부 확인
                spike_status = ""
                if coin['volume_spike_ratio'] > 3:
                    spike_status = " 🚀 *급등중*"
                elif coin['volume_spike_ratio'] > 2:
                    spike_status = " ⚡ *활발*"

                message += f"""*{i}. {coin_name}* {spike_status}
💰 현재가: {coin['current_price']:,.0f}원
📊 거래대금: {volume_krw_formatted}
{volume_emoji} 거래량 변화: {coin['volume_change_rate']:+.1f}%
{price_emoji} 가격 변화: {coin['price_change_rate']:+.1f}%
⚡ 최근 1시간 거래량 배율: {coin['volume_spike_ratio']:.1f}x

"""

            # 추가 분석 정보
            message += """📈 *분석 포인트*
• 거래대금 기준 상위 5개 코인
• 거래량 급증 코인 식별
• 가격 변동률과 거래량 상관관계 분석
• 실시간 시장 동향 파악

⚠️ *투자 주의사항*
거래량이 높다고 반드시 좋은 투자 기회는 아닙니다.
충분한 분석 후 신중한 투자 결정을 하시기 바랍니다."""

            # 메시지 전송
            await self.telegram_bot.send_message(message)

            # 차트 생성 및 전송
            chart_bytes = self.create_volume_chart(top_coins)
            if chart_bytes:
                await asyncio.sleep(1)  # API 제한 고려
                await self.telegram_bot.send_photo(
                    chart_bytes,
                    caption="거래량 상위 5개 코인 차트"
                )

            logger.info("거래량 분석 보고서 전송 완료")

        except Exception as e:
            logger.error(f"보고서 전송 실패: {str(e)}")
            await self.telegram_bot.send_message(f"❌ 보고서 전송 중 오류 발생: {str(e)}")

    async def run_analysis(self):
        """분석 실행"""
        try:
            logger.info("거래량 분석 시작")

            # 상위 5개 코인 분석
            top_coins = await self.analyze_top_volume_coins(5)

            if not top_coins:
                logger.error("분석할 데이터가 없습니다")
                await self.telegram_bot.send_message("❌ 거래량 데이터 수집 실패")
                return

            # 보고서 전송
            await self.send_volume_report(top_coins)

            logger.info("거래량 분석 완료")

        except Exception as e:
            logger.error(f"분석 실행 중 오류: {str(e)}")
            await self.telegram_bot.send_message(f"❌ 분석 실행 중 오류 발생: {str(e)}")

        finally:
            await self.telegram_bot.close()

    async def scheduled_analysis(self):
        """정기 분석 실행 (매일 9시, 15시, 21시)"""
        logger.info("정기 거래량 분석 스케줄러 시작")

        # 시작 메시지 전송
        await self.telegram_bot.send_message("🚀 *거래량 분석기 스케줄러가 시작되었습니다*\n📅 분석 시간: 매일 08:00, 12:00, 17:00, 21:00")

        while True:
            try:
                now = datetime.now()
                # 분석 실행 시간: 8시, 12tl, 17시, 21시
                if now.hour in [8, 12, 17, 21] and now.minute == 0:
                    await self.run_analysis()
                    await asyncio.sleep(3600)  # 1시간 대기 (중복 실행 방지)
                else:
                    await asyncio.sleep(60)  # 1분마다 시간 확인

            except KeyboardInterrupt:
                logger.info("스케줄러가 중지되었습니다")
                await self.telegram_bot.send_message("⛔ *거래량 분석기 스케줄러가 중지되었습니다*")
                break
            except Exception as e:
                logger.error(f"스케줄러 실행 중 오류: {str(e)}")
                await asyncio.sleep(300)  # 5분 대기 후 재시도


async def main():
    """메인 함수"""
    # 표준 입력에서 선택 읽기 (쉘 스크립트에서 전달)
    choice = None

    # 표준 입력이 있는지 확인
    if not sys.stdin.isatty():
        try:
            choice = input().strip()
        except EOFError:
            choice = None

    # 선택이 없으면 사용자에게 물어보기
    if choice is None:
        print("거래량 분석기 시작 옵션:")
        print("1. 즉시 분석 실행")
        print("2. 정기 분석 스케줄러 실행")
        choice = input("선택하세요 (1 또는 2): ").strip()

    analyzer = VolumeAnalyzer()

    try:
        if choice == "1":
            await analyzer.run_analysis()
        elif choice == "2":
            await analyzer.scheduled_analysis()
        else:
            print("잘못된 선택입니다. 즉시 분석을 실행합니다.")
            await analyzer.run_analysis()

    except KeyboardInterrupt:
        logger.info("프로그램이 종료되었습니다")
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {str(e)}")
    finally:
        await analyzer.telegram_bot.close()


if __name__ == "__main__":
    # 로그 폴더 생성
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # 프로그램 실행
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램이 종료되었습니다")
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {str(e)}")