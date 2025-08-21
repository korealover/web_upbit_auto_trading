# utils/telegram_utils.py
import logging
import asyncio
import aiohttp
from telegram import Bot
from telegram.request import HTTPXRequest
from config import Config
import requests
from functools import lru_cache
import threading
from concurrent.futures import ThreadPoolExecutor


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
        self.usename = usename
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TelegramNotifier")
        self._loop = None
        self._loop_thread = None
        self._shutdown = False
        self._initialize_async_components()

    def _initialize_async_components(self):
        """비동기 컴포넌트 초기화 - 개선된 버전"""
        try:
            # 새로운 이벤트 루프 생성
            self._loop = asyncio.new_event_loop()

            # 별도 스레드에서 이벤트 루프 실행
            def run_event_loop():
                asyncio.set_event_loop(self._loop)
                try:
                    self._loop.run_forever()
                except Exception as e:
                    self.logger.error(f"이벤트 루프 실행 중 오류: {e}")
                finally:
                    self._loop.close()

            self._loop_thread = threading.Thread(
                target=run_event_loop,
                daemon=True,
                name="TelegramNotifierLoop"
            )
            self._loop_thread.start()

            # 이벤트 루프가 시작될 때까지 잠시 대기
            import time
            time.sleep(0.1)

        except Exception as e:
            self.logger.error(f"비동기 컴포넌트 초기화 실패: {e}")
            self._loop = None

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

    def send_message(self, message):
        """메시지 전송 - 스레드 안전 버전"""
        try:
            self.logger.debug(f"텔레그램 메시지 전송 시도: {message[:30]}...")

            # 토큰과 채팅 ID 확인
            if not self.token or not self.chat_id:
                self.logger.error("텔레그램 토큰 또는 채팅 ID가 설정되지 않았습니다.")
                return False

            # 종료 상태 확인
            if self._shutdown:
                self.logger.warning("TelegramNotifier가 종료 상태입니다.")
                return False

            # 이벤트 루프가 있고 실행 중인지 확인
            if self._loop and not self._loop.is_closed():
                try:
                    # 코루틴을 별도 스레드의 이벤트 루프에서 실행
                    future = asyncio.run_coroutine_threadsafe(
                        self._send_message_async(message),
                        self._loop
                    )
                    # 결과 대기 (최대 10초)
                    result = future.result(timeout=10)
                    return result
                except Exception as e:
                    self.logger.error(f"이벤트 루프 실행 중 오류: {e}")
                    return False
            else:
                # 이벤트 루프가 없으면 동기 방식으로 전송 시도
                return self._send_message_sync(message)

        except Exception as e:
            self.logger.error(f"텔레그램 메시지 전송 중 오류: {str(e)}", exc_info=True)
            return False

    def _send_message_sync(self, message):
        """동기 방식으로 메시지 전송 (백업용)"""
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"동기 방식 메시지 전송 실패: {e}")
            return False

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

    def __del__(self):
        """소멸자에서 리소스 정리"""
        try:
            self._shutdown = True

            # 이벤트 루프 종료
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._loop.stop)

            # 스레드 종료 대기
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=1)

            # 스레드 풀 종료
            if hasattr(self, '_executor') and self._executor:
                self._executor.shutdown(wait=False)

        except Exception as e:
            if self.logger:
                self.logger.error(f"리소스 정리 중 오류: {str(e)}")