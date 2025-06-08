import time
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import telegram
import asyncio
import pyupbit
import logging
from config import Config
from logging.handlers import TimedRotatingFileHandler

# 로깅 설정
os.makedirs("logs", exist_ok=True)


# 로거 설정 함수 정의
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
        backupCount=30,  # 30일치 로그 파일 보존
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)

    # 파일명 패턴 설정 (파일명.log.YYYY-MM-DD 형식으로 변경)
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

# 텔레그램 봇 설정
bot = telegram.Bot(token=Config.TELEGRAM_BOT_TOKEN)
chat_id = Config.TELEGRAM_CHAT_ID

# 업비트 API 설정
upbit = pyupbit.Upbit(Config.UPBIT_ACCESS_KEY, Config.UPBIT_SECRET_KEY)

# 전역 변수로 티커 목록 설정
tickers = []

# 시간 체크를 위한 마지막 보고서 전송 시간 (초기값은 과거)
last_report_time = datetime(2025, 6, 1)


async def send_message(text):
    """텔레그램으로 메시지 전송"""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        logger.info("텔레그램 메시지 전송 성공")
    except Exception as e:
        logger.error(f"텔레그램 메시지 전송 실패: {str(e)}")


async def send_photo(image_path):
    """텔레그램으로 이미지 전송"""
    try:
        with open(image_path, 'rb') as photo:
            await bot.send_photo(chat_id=chat_id, photo=photo)
        logger.info("텔레그램 이미지 전송 성공")
        # 전송 후 이미지 파일 삭제
        os.remove(image_path)
    except Exception as e:
        logger.error(f"텔레그램 이미지 전송 실패: {str(e)}")


def create_chart(ticker, interval='day', count=30):
    """코인 차트 생성 및 저장"""
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
        plt.plot(df.index, df['close'], label='Price', color='black')
        plt.plot(df.index, df['middle'], label='MA20', color='blue', alpha=0.5)
        plt.plot(df.index, df['upper'], label='Upper Band', color='red', alpha=0.5)
        plt.plot(df.index, df['lower'], label='Lower Band', color='green', alpha=0.5)

        # 현재가 마커
        current_price = df['close'].iloc[-1]
        plt.scatter(df.index[-1], current_price, color='blue', s=80, zorder=5)

        # 제목 및 레이블
        plt.title(f'{ticker} Price Chart ({interval})', fontsize=16)
        plt.xlabel('Date')
        plt.ylabel('Price (KRW)')
        plt.legend()
        plt.grid(alpha=0.3)

        # 파일 저장
        chart_path = f"./temp_{ticker.replace('-', '_')}_{int(time.time())}.png"
        plt.savefig(chart_path)
        plt.close()

        return chart_path, df
    except Exception as e:
        logger.error(f"차트 생성 실패: {str(e)}")
        return None, None


def get_coin_info(ticker):
    """코인 정보 가져오기"""
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

            # 거래량 (당일 데이터)
            volume = df.iloc[-1]['volume']
        else:
            change_rate = 0
            volume = 0

        # 잔고 정보
        balance_coin = upbit.get_balance(ticker)
        balance_krw = upbit.get_balance("KRW")
        avg_buy_price = upbit.get_avg_buy_price(ticker)

        # 평가금액 및 수익률
        evaluation = balance_coin * current_price
        profit_loss = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0

        # 정보 반환
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
    """코인 보고서 전송"""
    try:
        # 코인 정보 가져오기
        coin_info = get_coin_info(ticker)
        if not coin_info:
            await send_message(f"❌ {ticker} 정보를 가져오는데 실패했습니다.")
            return

        # 차트 생성
        chart_path, df = create_chart(ticker, interval)
        if not chart_path or df is None or len(df) == 0:
            await send_message(f"❌ {ticker} 차트를 생성하는데 실패했습니다.")
            return

        # 기술적 지표 분석
        last_price = df['close'].iloc[-1]
        ma20 = df['middle'].iloc[-1]
        upper_band = df['upper'].iloc[-1]
        lower_band = df['lower'].iloc[-1]

        if last_price > upper_band:
            technical_status = "매도 고려 📈 (상단밴드 돌파)"
        elif last_price < lower_band:
            technical_status = "매수 고려 📉 (하단밴드 돌파)"
        else:
            technical_status = "관망 ⏱️ (밴드 내 이동 중)"

        # 메시지 생성
        message = f"""
*{ticker} 코인 보고서* ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

*💰 가격 정보*
현재가: {coin_info['current_price']:,.0f} KRW
24시간 변동률: {coin_info['change_rate_24h']:.2f}%
24시간 거래량: {coin_info['volume_24h']:.4f} {ticker.split('-')[1]}

*💼 보유 정보*
보유수량: {coin_info['balance_coin']:.8f} {ticker.split('-')[1]}
평균매수가: {coin_info['avg_buy_price']:,.0f} KRW
평가금액: {coin_info['evaluation']:,.0f} KRW
수익률: {coin_info['profit_loss']:.2f}%
보유 현금: {coin_info['balance_krw']:,.0f} KRW

*📊 기술적 분석*
현재 상태: {technical_status}
이동평균(MA20): {ma20:,.0f} KRW
상단밴드: {upper_band:,.0f} KRW
하단밴드: {lower_band:,.0f} KRW
        """

        # 정보 전송
        await send_message(message)
        await send_photo(chart_path)

    except Exception as e:
        logger.error(f"코인 보고서 전송 실패: {str(e)}")
        await send_message(f"❌ 오류 발생: {str(e)}")


async def send_all_reports():
    """모든 코인에 대한 보고서 전송"""
    global last_report_time

    logger.info(f"정해진 시간에 모든 코인 보고서 전송 시작")
    last_report_time = datetime.now()  # 마지막 전송 시간 업데이트

    for ticker in tickers:
        logger.info(f"{ticker} 정보 전송 중...")
        await send_coin_report(ticker)
        # 연속 요청 방지를 위한 대기
        await asyncio.sleep(5)

    logger.info("모든 코인 보고서 전송 완료")


async def setup():
    """초기 설정 및 시작 메시지 전송"""
    global tickers

    # 보유 중인 모든 코인 정보 가져오기
    try:
        account_info = upbit.get_balances()

        # 궁금한 코인들
        list_tickers = ["KRW-ETH", "KRW-XLM"]
        # list_tickers = []
        # 보유중인 코인들
        for coin in account_info:
            if coin['currency'] != 'KRW':  # KRW는 제외
                ticker = f"KRW-{coin['currency']}"
                list_tickers.append(ticker)

        set_tickers = set(list_tickers)
        tickers = list(set_tickers)

        logger.info(f"모니터링할 코인 목록: {tickers}")

        # 시작 메시지 전송
        await send_message("✅ *코인 모니터링 시스템이 시작되었습니다.*")
    except Exception as e:
        logger.error(f"초기 설정 중 오류 발생: {str(e)}")
        await send_message(f"⚠️ *초기 설정 중 오류 발생:* {str(e)}")


def is_report_time():
    """현재 시간이 보고서를 보낼 시간인지 확인"""
    now = datetime.now()
    # 10시 ~ 22시에 보고서 전송
    report_times = [
        (10, 0),  # 10시 정각
        (12, 0),  # 12시 정각
        (14, 0),  # 14시 정각
        (16, 0),  # 16시 정각
        (18, 0),  # 18시 정각
        (20, 0),  # 20시 정각
        (22, 0)  # 22시 정각
    ]

    # 현재 시간이 보고서 전송 시간인지 확인
    for hour, minute in report_times:
        if now.hour == hour and now.minute == minute:
            # 같은 분에 한 번만 전송하기 위해 마지막 전송 시간 확인
            time_diff = now - last_report_time
            # 마지막 전송이 5분 이상 전이면 전송
            if time_diff.total_seconds() > 300:
                return True
    return False


async def main():
    """메인 함수"""
    try:
        # 초기 설정 실행
        await setup()

        # 예약 작업 시작 메시지
        logger.info("모니터링이 시작되었습니다. 지정된 시간에 보고서가 전송됩니다.")

        # 무한 루프로 시간 확인 및 보고서 전송
        while True:
            try:
                # 현재 시간이 보고서 전송 시간인지 확인
                if is_report_time():
                    await send_all_reports()

                # 1분마다 확인
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # asyncio.CancelledError는 정상적인 종료로 처리
                logger.info("작업이 취소되었습니다.")
                break
            except Exception as e:
                logger.error(f"루프 실행 중 오류 발생: {str(e)}")
                await send_message(f"⚠️ *오류가 발생했지만 모니터링은 계속됩니다:* {str(e)}")
                await asyncio.sleep(60)  # 오류 발생 시에도 계속 실행

    except KeyboardInterrupt:
        logger.info("사용자에 의해 프로그램이 종료되었습니다.")
        await send_message("⛔ *코인 모니터링 시스템이 중지되었습니다.*")
    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {str(e)}")
        # 여기서 send_all_reports를 직접 호출하지 않도록 수정
        await send_message(f"⚠️ *오류로 인해 모니터링이 중지되었습니다:* {str(e)}")


if __name__ == "__main__":
    # 임시 저장 폴더 확인
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # asyncio 실행
    asyncio.run(main())