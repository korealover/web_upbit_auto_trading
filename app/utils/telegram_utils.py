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
import weakref
import time


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


class TelegramNotifier:
    """텔레그램 알림 클래스 (최적화)"""

    _instances = weakref.WeakSet()
    _global_loop = None
    _global_loop_thread = None
    _loop_lock = threading.Lock()

    def __init__(self, token, chat_id, logger=None, usename=None):
        """텔레그램 알림 초기화"""
        self.token = token
        self.chat_id = chat_id
        self.bot = get_telegram_bot(token)
        self.logger = logger or logging.getLogger(__name__)
        self.usename = usename
        self._shutdown = False

        # 전역 이벤트 루프 사용
        self._ensure_global_loop()
        TelegramNotifier._instances.add(self)

    @classmethod
    def _ensure_global_loop(cls):
        """전역 이벤트 루프 보장"""
        with cls._loop_lock:
            if cls._global_loop is None or cls._global_loop.is_closed():
                cls._create_global_loop()

    @classmethod
    def _create_global_loop(cls):
        """전역 이벤트 루프 생성"""
        try:
            # 기존 루프 정리
            if cls._global_loop_thread and cls._global_loop_thread.is_alive():
                if cls._global_loop and not cls._global_loop.is_closed():
                    cls._global_loop.call_soon_threadsafe(cls._global_loop.stop)
                cls._global_loop_thread.join(timeout=2)

            # 새 이벤트 루프 생성
            cls._global_loop = asyncio.new_event_loop()

            def run_event_loop():
                asyncio.set_event_loop(cls._global_loop)
                try:
                    cls._global_loop.run_forever()
                except Exception as e:
                    logging.error(f"전역 이벤트 루프 실행 중 오류: {e}")
                finally:
                    cls._global_loop.close()

            cls._global_loop_thread = threading.Thread(
                target=run_event_loop,
                daemon=True,
                name="GlobalTelegramLoop"
            )
            cls._global_loop_thread.start()

            # 루프 시작 대기
            time.sleep(0.1)

        except Exception as e:
            logging.error(f"전역 이벤트 루프 생성 실패: {e}")
            cls._global_loop = None

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
        """메시지 전송 - 개선된 버전"""
        try:
            self.logger.debug(f"텔레그램 메시지 전송 시도: {message[:30]}...")

            # 기본 검증
            if not self.token or not self.chat_id:
                self.logger.error("텔레그램 토큰 또는 채팅 ID가 설정되지 않았습니다.")
                return False

            if self._shutdown:
                self.logger.warning("TelegramNotifier가 종료 상태입니다.")
                return False

            # 전역 루프 확인 및 재생성
            if (self._global_loop is None or
                    self._global_loop.is_closed() or
                    not self._global_loop_thread.is_alive()):
                self.logger.info("이벤트 루프 재생성 중...")
                self._ensure_global_loop()

            # 비동기 메시지 전송
            if self._global_loop and not self._global_loop.is_closed():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._send_message_async(message),
                        self._global_loop
                    )
                    result = future.result(timeout=15)
                    return result
                except Exception as e:
                    self.logger.error(f"비동기 전송 실패: {e}")
                    # 동기 방식으로 대체
                    return self._send_message_sync(message)
            else:
                return self._send_message_sync(message)

        except Exception as e:
            self.logger.error(f"텔레그램 메시지 전송 중 오류: {str(e)}", exc_info=True)
            return self._send_message_sync(message)

    def _send_message_sync(self, message):
        """동기 방식으로 메시지 전송 (백업용)"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                self.logger.debug("동기 방식으로 메시지 전송 성공")
                return True
            else:
                self.logger.error(f"동기 전송 실패 - 상태코드: {response.status_code}")
                return False
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

    @classmethod
    def shutdown_all(cls):
        """모든 인스턴스 종료"""
        with cls._loop_lock:
            # 모든 인스턴스 종료 플래그 설정
            for instance in cls._instances:
                instance._shutdown = True

            # 전역 루프 종료
            if cls._global_loop and not cls._global_loop.is_closed():
                cls._global_loop.call_soon_threadsafe(cls._global_loop.stop)

            # 스레드 종료 대기
            if cls._global_loop_thread and cls._global_loop_thread.is_alive():
                cls._global_loop_thread.join(timeout=3)

            cls._global_loop = None
            cls._global_loop_thread = None

    def __del__(self):
        """소멸자에서 개별 인스턴스 정리"""
        self._shutdown = True