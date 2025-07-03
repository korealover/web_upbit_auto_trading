import time
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import asyncio
import pyupbit
import logging
from config import Config
from logging.handlers import TimedRotatingFileHandler
import aiohttp
import json
from io import BytesIO

# matplotlib 한글 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

# 로깅 설정
os.makedirs("logs", exist_ok=True)


def setup_logger():
    """일별 로그 파일 자동 생성을 위한 로깅 설정"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # 이미 핸들러가 있다면 모두 제거
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 파일 핸들러 (매일 자정에 자동으로 새 파일 생성)
    log_file = os.path.join("logs", "coin_monitor.log")
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

# 업비트 API 설정
upbit = pyupbit.Upbit(Config.UPBIT_ACCESS_KEY, Config.UPBIT_SECRET_KEY)

# 전역 변수
tickers = []
last_report_time = datetime(2025, 6, 1)


class TelegramBot:
    """텔레그램 봇 클래스 - 수정된 버전"""

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
            data.add_field('photo', photo_bytes, filename='chart.png', content_type='image/png')

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


# 텔레그램 봇 인스턴스
telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID_PERSONAL)


def create_chart(ticker, interval='day', count=30):
    """코인 차트 생성 및 바이트 반환"""
    try:
        # OHLCV 데이터 가져오기
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
        if df is None or len(df) == 0:
            logger.error(f"{ticker} OHLCV 데이터를 가져오지 못했습니다.")
            return None, None

        # 볼린저 밴드 계산
        window = 20
        df['middle'] = df['close'].rolling(window=window).mean()
        std = df['close'].rolling(window=window).std()
        df['upper'] = df['middle'] + 2 * std
        df['lower'] = df['middle'] - 2 * std

        # 차트 그리기
        plt.figure(figsize=(12, 6))

        # 가격 차트
        plt.plot(df.index, df['close'], label='Price', color='black', linewidth=2)
        plt.plot(df.index, df['middle'], label='MA20', color='blue', alpha=0.7)
        plt.plot(df.index, df['upper'], label='Upper Band', color='red', alpha=0.7)
        plt.plot(df.index, df['lower'], label='Lower Band', color='green', alpha=0.7)

        # 현재가 마커
        current_price = df['close'].iloc[-1]
        plt.scatter(df.index[-1], current_price, color='blue', s=100, zorder=5)

        # 제목 및 레이블
        plt.title(f'{ticker} Price Chart ({interval})', fontsize=16, fontweight='bold')
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Price (KRW)', fontsize=12)
        plt.legend(fontsize=10)
        plt.grid(alpha=0.3)
        plt.tight_layout()

        # 바이트로 변환
        img_buffer = BytesIO()
        plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()

        return img_buffer.getvalue(), df

    except Exception as e:
        logger.error(f"차트 생성 실패: {str(e)}")
        plt.close()  # 에러 시에도 plt 정리
        return None, None


def get_coin_info(ticker):
    """코인 정보 가져오기 - 개선된 버전"""
    try:
        # 현재가
        current_price = pyupbit.get_current_price(ticker)
        if current_price is None:
            logger.error(f"{ticker} 현재가를 가져오지 못했습니다.")
            return None

        # OHLCV 데이터를 통해 24시간 변동률 계산
        df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
        if df is not None and len(df) >= 1:
            yesterday_close = df.iloc[-2]['close'] if len(df) > 1 else df.iloc[0]['open']
            change_rate = ((current_price - yesterday_close) / yesterday_close * 100)
            volume = df.iloc[-1]['volume']
        else:
            change_rate = 0
            volume = 0

        # 잔고 정보
        try:
            balance_coin = upbit.get_balance(ticker)
            balance_krw = upbit.get_balance("KRW")
            avg_buy_price = upbit.get_avg_buy_price(ticker)
        except Exception as e:
            logger.warning(f"잔고 정보 가져오기 실패: {str(e)}")
            balance_coin = 0
            balance_krw = 0
            avg_buy_price = 0

        # 평가금액 및 수익률
        evaluation = balance_coin * current_price
        profit_loss = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0

        return {
            "ticker": ticker,
            "current_price": current_price,
            "change_rate_24h": change_rate,
            "volume_24h": volume,
            "balance_coin": balance_coin,
            "balance_krw": balance_krw,
            "avg_buy_price": avg_buy_price,
            "evaluation": evaluation,
            "profit_loss": profit_loss
        }

    except Exception as e:
        logger.error(f"코인 정보 가져오기 실패: {str(e)}")
        return None


async def send_coin_report(ticker, interval='day'):
    """코인 보고서 전송 - 개선된 버전"""
    try:
        # 코인 정보 가져오기
        coin_info = get_coin_info(ticker)
        if not coin_info:
            await telegram_bot.send_message(f"❌ {ticker} 정보를 가져오는데 실패했습니다.")
            return

        # 차트 생성
        chart_bytes, df = create_chart(ticker, interval)
        if not chart_bytes or df is None or len(df) == 0:
            await telegram_bot.send_message(f"❌ {ticker} 차트를 생성하는데 실패했습니다.")
            return

        # 기술적 지표 분석
        last_price = df['close'].iloc[-1]
        ma20 = df['middle'].iloc[-1] if not pd.isna(df['middle'].iloc[-1]) else last_price
        upper_band = df['upper'].iloc[-1] if not pd.isna(df['upper'].iloc[-1]) else last_price
        lower_band = df['lower'].iloc[-1] if not pd.isna(df['lower'].iloc[-1]) else last_price

        if last_price > upper_band:
            technical_status = "매도 고려 📈 (상단밴드 돌파)"
        elif last_price < lower_band:
            technical_status = "매수 고려 📉 (하단밴드 돌파)"
        else:
            technical_status = "관망 ⏱️ (밴드 내 이동 중)"

        # 메시지 생성
        coin_symbol = ticker.split('-')[1] if '-' in ticker else ticker
        message = f"""*{coin_symbol} 코인 보고서*
📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*💰 가격 정보*
현재가: {coin_info['current_price']:,.0f} KRW
24시간 변동률: {coin_info['change_rate_24h']:+.2f}%
24시간 거래량: {coin_info['volume_24h']:.4f} {coin_symbol}

*💼 보유 정보*
보유수량: {coin_info['balance_coin']:.8f} {coin_symbol}
평균매수가: {coin_info['avg_buy_price']:,.0f} KRW
평가금액: {coin_info['evaluation']:,.0f} KRW
수익률: {coin_info['profit_loss']:+.2f}%
보유 현금: {coin_info['balance_krw']:,.0f} KRW

*📊 기술적 분석*
현재 상태: {technical_status}
이동평균(MA20): {ma20:,.0f} KRW
상단밴드: {upper_band:,.0f} KRW
하단밴드: {lower_band:,.0f} KRW"""

        # 메시지와 차트 전송
        await telegram_bot.send_message(message)
        await asyncio.sleep(1)  # API 제한 고려
        await telegram_bot.send_photo(chart_bytes, caption=f"{coin_symbol} 차트")

    except Exception as e:
        logger.error(f"코인 보고서 전송 실패: {str(e)}")
        await telegram_bot.send_message(f"❌ {ticker} 보고서 전송 중 오류 발생: {str(e)}")


async def send_all_reports():
    """모든 코인에 대한 보고서 전송"""
    global last_report_time

    logger.info("정해진 시간에 모든 코인 보고서 전송 시작")
    last_report_time = datetime.now()

    for i, ticker in enumerate(tickers):
        try:
            logger.info(f"{ticker} 정보 전송 중... ({i + 1}/{len(tickers)})")
            await send_coin_report(ticker)
            # 연속 요청 방지를 위한 대기 (마지막 코인이 아닌 경우)
            if i < len(tickers) - 1:
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"{ticker} 보고서 전송 중 오류: {str(e)}")
            continue

    logger.info("모든 코인 보고서 전송 완료")


async def setup():
    """초기 설정 및 시작 메시지 전송"""
    global tickers

    try:
        # 보유 중인 모든 코인 정보 가져오기
        account_info = upbit.get_balances()
        logger.info(f"계정 정보 타입: {type(account_info)}")

        if account_info is None:
            logger.warning("계정 정보를 가져올 수 없습니다.")
            account_info = []
        elif isinstance(account_info, str):
            try:
                logger.info(f"계정 정보(문자열): {account_info[:100]}...")
                account_info = json.loads(account_info)
                logger.info("JSON 파싱 성공")
            except json.JSONDecodeError:
                logger.error("계정 정보를 JSON으로 파싱할 수 없습니다.")
                account_info = []

        # 모니터링할 코인들 설정
        list_tickers = []

        # 보유중인 코인들 추가
        if isinstance(account_info, list):
            for coin in account_info:
                if isinstance(coin, dict) and 'currency' in coin and coin['currency'] != 'KRW':
                    balance = float(coin.get('balance', 0))
                    if balance > 0:  # 실제 보유량이 있는 코인만
                        ticker = f"KRW-{coin['currency']}"
                        list_tickers.append(ticker)
                        logger.info(f"보유 코인 추가: {ticker} (보유량: {balance})")

        # 관심 코인들 추가 (필요시 주석 해제)
        # list_tickers.extend(["KRW-ETH", "KRW-XLM"])

        tickers = list(set(list_tickers))  # 중복 제거
        logger.info(f"모니터링할 코인 목록: {tickers}")

        # 시작 메시지 전송
        start_message = f"""✅ *코인 모니터링 시스템 시작*
📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 모니터링 코인: {len(tickers)}개
🕙 보고서 전송 시간: 8시, 10시, 12시, 14시, 16시, 18시, 20시, 22시

모니터링 대상:
{chr(10).join([f"• {ticker.split('-')[1]}" for ticker in tickers[:10]])}
{'• ...' if len(tickers) > 10 else ''}
"""
        await telegram_bot.send_message(start_message)

    except Exception as e:
        logger.error(f"초기 설정 중 오류 발생: {str(e)}", exc_info=True)
        await telegram_bot.send_message(f"⚠️ *초기 설정 중 오류 발생:* {str(e)}")


def is_report_time():
    """현재 시간이 보고서를 보낼 시간인지 확인"""
    now = datetime.now()
    report_times = [(8, 0), (10, 0), (12, 0), (14, 0), (16, 0), (18, 0), (20, 0), (22, 0)]

    for hour, minute in report_times:
        if now.hour == hour and now.minute == minute:
            time_diff = now - last_report_time
            if time_diff.total_seconds() > 300:  # 5분 이상 차이
                return True
    return False


async def main():
    """메인 함수"""
    try:
        # 초기 설정 실행
        await setup()

        logger.info("모니터링이 시작되었습니다. 지정된 시간에 보고서가 전송됩니다.")

        # 무한 루프로 시간 확인 및 보고서 전송
        while True:
            try:
                if is_report_time():
                    await send_all_reports()

                await asyncio.sleep(60)  # 1분마다 확인

            except KeyboardInterrupt:
                logger.info("사용자에 의해 프로그램이 종료되었습니다.")
                await telegram_bot.send_message("⛔ *코인 모니터링 시스템이 중지되었습니다.*")
                break
            except Exception as e:
                logger.error(f"루프 실행 중 오류 발생: {str(e)}")
                await telegram_bot.send_message(f"⚠️ *오류가 발생했지만 모니터링은 계속됩니다:* {str(e)}")
                await asyncio.sleep(60)

    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {str(e)}")
        await telegram_bot.send_message(f"⚠️ *오류로 인해 모니터링이 중지되었습니다:* {str(e)}")
    finally:
        # 리소스 정리
        await telegram_bot.close()


if __name__ == "__main__":
    # 임시 저장 폴더 확인
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # asyncio 실행
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램이 종료되었습니다.")
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {str(e)}")