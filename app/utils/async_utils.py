import asyncio
import concurrent.futures
import functools
from config import Config

class AsyncHandler:
    """비동기 작업 처리 핸들러 (최적화)"""

    def __init__(self, max_workers=Config.MAX_WORKERS, thread_name_prefix=Config.THREAD_NAME_PREFIX):
        """초기화 - 스레드 풀 옵션 개선"""
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix
        )
        self._loop = None

    def _get_event_loop(self):
        """이벤트 루프 관리 개선"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    async def run_async(self, func, max_retries=5, delay=0.5, logger=None, backoff_factor=2):
        """비동기 방식으로 함수 실행 - 지수 백오프 추가"""
        for i in range(max_retries):
            try:
                # 스레드 풀에서 함수 실행
                result = await asyncio.get_event_loop().run_in_executor(self.executor, func)

                if result is not None:
                    return result

                if logger:
                    logger.debug(f"데이터 가져오기 재시도 중... ({i + 1}/{max_retries}) - 결과: {result}")

                # 지수 백오프 적용
                current_delay = delay * (backoff_factor ** i)
                await asyncio.sleep(current_delay)

            except Exception as e:
                if logger:
                    # 디버깅을 위한 상세 정보
                    import traceback
                    error_details = {
                        'exception_type': type(e).__name__,
                        'exception_str': str(e),
                        'exception_repr': repr(e),
                        'traceback': traceback.format_exc()
                    }
                    logger.error(f"데이터 가져오기 실패 상세: {error_details}")

                # 오류 유형에 따라 대기 시간 조정
                if "Too many API requests" in str(e):
                    await asyncio.sleep(delay * 5 * (backoff_factor ** i))
                else:
                    await asyncio.sleep(delay * (backoff_factor ** i))

        if logger:
            logger.error(f"최대 재시도 횟수({max_retries})를 초과했습니다.")
        return None

    def run_sync(self, func, max_retries=5, delay=0.5, logger=None, backoff_factor=2):
        """동기 방식으로 비동기 함수 실행 - 이벤트 루프 관리 개선"""
        loop = self._get_event_loop()
        if not self._loop:
            self._loop = loop

        try:
            return loop.run_until_complete(
                self.run_async(func, max_retries, delay, logger, backoff_factor)
            )
        except RuntimeError as e:
            # 이미 실행 중인 이벤트 루프 처리
            if "This event loop is already running" in str(e) and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.run_async(func, max_retries, delay, logger, backoff_factor),
                    loop
                )
                return future.result(timeout=30)
            raise

    def shutdown(self, wait=True):
        """스레드 풀 종료 - wait 옵션 추가"""
        self.executor.shutdown(wait=wait)
