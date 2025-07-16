# utils/telegram_utils.py
import logging
import asyncio
import aiohttp
from telegram import Bot
from telegram.request import HTTPXRequest
from config import Config
import requests
from functools import lru_cache


@lru_cache(maxsize=1)
def get_telegram_bot(token):
    """텔레그램 봇 인스턴스 캐싱"""
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=10.0,
        read_timeout=30.0,
        pool_timeout=3.0
    )
    return Bot(token=token, request=request)

# TelegramNotifier 클래스
class TelegramNotifier:
    """텔레그램 알림 클래스 (최적화)"""

    def __init__(self, token, chat_id, logger=None, usename=None):
        """텔레그램 알림 초기화"""
        self.token = token
        self.chat_id = chat_id
        self.bot = get_telegram_bot(token)
        self.logger = logger or logging.getLogger(__name__)
        self._session = None
        self._message_queue = asyncio.Queue()
        self._is_sending = False
        self._loop = None
        self._sender_task = None
        self._initialize_async_components()
        self.usename = usename

    def _initialize_async_components(self):
            """비동기 컴포넌트 초기화"""
            try:
                # 메인 스레드에서 실행 중인 경우
                self._loop = asyncio.get_event_loop()
                if self._loop.is_closed():
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)
            except RuntimeError:
                # 새 이벤트 루프 생성
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

            # 새로운 방식: 별도의 스레드에서 이벤트 루프 실행
            def run_event_loop():
                asyncio.set_event_loop(self._loop)
                self._loop.run_forever()

            import threading
            self._loop_thread = threading.Thread(target=run_event_loop, daemon=True, name="TelegramNotifierLoopThread")
            self._loop_thread.start()

    async def _get_session(self):
        """비동기 HTTP 세션 관리"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _send_message_async(self, message):
        """비동기로 메시지 전송"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True
        except Exception as e:
            self.logger.error(f"텔레그램 메시지 전송 실패: {str(e)}")
            return False

    async def _message_sender(self):
        """메시지 큐 처리기"""
        self._is_sending = True
        try:
            while True:
                message = await self._message_queue.get()
                if message is None:
                    break

                try:
                    await self._send_message_async(message)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    self.logger.error(f"메시지 전송 중 오류: {str(e)}")
                finally:
                    self._message_queue.task_done()
        finally:
            self._is_sending = False


    def _ensure_sender_task(self):
        """메시지 전송 태스크 확인"""
        if not self._is_sending:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            self._loop = loop
            asyncio.create_task(self._message_sender())

    def send_message(self, message):
        """메시지 전송 - 수정된 버전"""
        try:
            self.logger.debug(f"텔레그램 메시지 전송 시도: {message[:30]}...")

            # 토큰과 채팅 ID 확인
            if not self.token or not self.chat_id:
                self.logger.error("텔레그램 토큰 또는 채팅 ID가 설정되지 않았습니다.")
                return False

                # 기존 이벤트 루프 재사용
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                # 새 이벤트 루프 생성
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # 이벤트 루프가 실행 중인지 확인
            if not loop.is_running():
                # 이벤트 루프가 실행 중이 아니면 코루틴 실행
                loop.run_until_complete(self._send_message_async(message))
            else:
                # 이벤트 루프가 실행 중이면 태스크로 추가
                future = asyncio.run_coroutine_threadsafe(
                    self._send_message_async(message),
                    loop
                )
                # 결과 대기 (최대 10초)
                future.result(10)

            return True
        except Exception as e:
            self.logger.error(f"텔레그램 메시지 전송 중 오류: {str(e)}", exc_info=True)
            return False


    def __del__(self):
        """소멸자에서 리소스 정리"""
        try:
            if self._loop and not self._loop.is_closed():
                if self._session and not self._session.closed:
                    asyncio.run_coroutine_threadsafe(
                        self._session.close(),
                        self._loop
                    )
                if self._sender_task and not self._sender_task.done():
                    self._sender_task.cancel()
        except Exception as e:
            if self.logger:
                self.logger.error(f"리소스 정리 중 오류: {str(e)}")

    def send_trade_message(self, trade_type, ticker, amount, price=None, volume=None):
        """
        거래 알림 전송

        Args:
            trade_type (str): 거래 유형 ('매수' 또는 '매도')
            ticker (str): 코인 티커
            amount (float): 거래 금액 또는 수량
            price (float, optional): 거래 가격
            volume (float, optional): 거래 수량 (매수 시)

        Returns:
            bool: 전송 성공 여부
        """
        coin_symbol = ticker.split('-')[1] if '-' in ticker else ticker

        if trade_type == '매수':
            message = (
                f"🔵 *매수 완료*\n"
                f"───────────\n"
                f"• 매수자: `{self.usename}`\n"
                f"• 코인: `{coin_symbol}`\n"
                f"• 금액: `{amount:,.0f}원`\n"
            )
            if price:
                message += f"• 단가: `{price:,.2f}원`\n"
            if volume:
                message += f"• 수량: `{volume}`\n"

        elif trade_type == '매도':
            message = (
                f"🔴 *매도 완료*\n"
                f"───────────\n"
                f"• 매도자: `{self.usename}`\n"
                f"• 코인: `{coin_symbol}`\n"
                f"• 수량: `{amount}`\n"
            )
            if price:
                message += f"• 단가: `{price:,.2f}원`\n"
            if volume:
                message += f"• 금액: `{volume:,.0f}원`\n"

        else:
            message = f"거래 알림: {trade_type} {ticker} {amount}"

        return self.send_message(message)