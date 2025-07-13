# app/utils/thread_controller.py
import threading
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from app.utils.shared import trading_bots, lock

@dataclass
class ThreadStopResult:
    """스레드 중지 결과"""
    success: bool
    thread_id: Optional[int] = None
    user_id: Optional[int] = None
    ticker: Optional[str] = None
    message: str = ""
    stop_time: datetime = None

class ThreadController:
    """스레드 제어 클래스"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.stop_requests: Dict[str, bool] = {}  # 중지 요청 추적
        self.stop_history: List[ThreadStopResult] = []  # 중지 이력
        
    def stop_specific_thread(self, user_id: int, ticker: str, force: bool = False) -> ThreadStopResult:
        """특정 사용자의 특정 티커 스레드 중지"""
        try:
            with lock:
                # 스레드 존재 확인
                if user_id not in trading_bots or ticker not in trading_bots[user_id]:
                    return ThreadStopResult(
                        success=False,
                        user_id=user_id,
                        ticker=ticker,
                        message=f"스레드를 찾을 수 없습니다: User {user_id}, Ticker {ticker}",
                        stop_time=datetime.now()
                    )
                
                # 실행 플래그를 False로 설정
                trading_bots[user_id][ticker]["running"] = False
                
                # 중지 요청 기록
                stop_key = f"{user_id}_{ticker}"
                self.stop_requests[stop_key] = True
                
                # 스레드 ID 가져오기
                thread_id = trading_bots[user_id][ticker].get("thread_id")
                
                self.logger.info(f"스레드 중지 요청: User {user_id}, Ticker {ticker}, Thread ID: {thread_id}")
                
                # 강제 중지인 경우 스레드를 바로 제거
                if force:
                    del trading_bots[user_id][ticker]
                    self.logger.warning(f"강제 스레드 제거: User {user_id}, Ticker {ticker}")
                
                result = ThreadStopResult(
                    success=True,
                    thread_id=thread_id,
                    user_id=user_id,
                    ticker=ticker,
                    message=f"스레드 중지 {'(강제)' if force else '(정상)'}: {ticker}",
                    stop_time=datetime.now()
                )
                
                self.stop_history.append(result)
                return result
                
        except Exception as e:
            error_msg = f"스레드 중지 중 오류: {str(e)}"
            self.logger.error(error_msg)
            return ThreadStopResult(
                success=False,
                user_id=user_id,
                ticker=ticker,
                message=error_msg,
                stop_time=datetime.now()
            )

    def stop_user_threads(self, user_id, ticker_filter=None):
        """특정 사용자의 스레드 중지 (선택적으로 티커 필터 적용)"""
        try:
            results = []
            user_threads = []

            # 현재 실행 중인 스레드에서 해당 사용자의 스레드 찾기
            for thread in threading.enumerate():
                if hasattr(thread, 'user_id') and thread.user_id == user_id:
                    # 티커 필터가 있으면 해당 티커만 선택
                    if ticker_filter is None or (hasattr(thread, 'ticker') and thread.ticker == ticker_filter):
                        user_threads.append(thread)

            if not user_threads:
                self.logger.info(f"사용자 {user_id}의 실행 중인 스레드를 찾을 수 없습니다{' (티커: ' + ticker_filter + ')' if ticker_filter else ''}")
                return results

            # 각 스레드에 대해 중지 요청
            for thread in user_threads:
                try:
                    thread_id = getattr(thread, 'thread_id', thread.name)
                    ticker = getattr(thread, 'ticker', 'Unknown')

                    # 스레드 중지 플래그 설정
                    if hasattr(thread, 'stop_event'):
                        thread.stop_event.set()

                    # 스레드 종료 대기 (타임아웃 설정)
                    if thread.is_alive():
                        thread.join(timeout=5.0)

                    # 결과 확인
                    if not thread.is_alive():
                        result = ThreadStopResult(
                            success=True,
                            thread_id=thread_id,
                            user_id=user_id,
                            ticker=ticker,
                            message=f"스레드가 성공적으로 중지되었습니다.",
                            stop_time=datetime.now()
                        )
                        self.logger.info(f"사용자 {user_id}의 스레드 중지 성공: {thread_id}")
                    else:
                        result = ThreadStopResult(
                            success=False,
                            thread_id=thread_id,
                            user_id=user_id,
                            ticker=ticker,
                            message=f"스레드 중지 타임아웃",
                            stop_time=datetime.now()
                        )
                        self.logger.warning(f"사용자 {user_id}의 스레드 중지 타임아웃: {thread_id}")

                    results.append(result)
                    self.stop_history.append(result)

                except Exception as e:
                    result = ThreadStopResult(
                        success=False,
                        thread_id=getattr(thread, 'thread_id', thread.name),
                        user_id=user_id,
                        ticker=getattr(thread, 'ticker', 'Unknown'),
                        message=f"스레드 중지 오류: {str(e)}",
                        stop_time=datetime.now()
                    )
                    results.append(result)
                    self.stop_history.append(result)
                    self.logger.error(f"사용자 {user_id}의 스레드 중지 오류: {e}")

            return results

        except Exception as e:
            self.logger.error(f"사용자 스레드 중지 중 오류 발생: {e}")
            return []
    
    def stop_all_threads(self, force: bool = False) -> List[ThreadStopResult]:
        """모든 거래 스레드 중지"""
        results = []
        
        try:
            # 전역 종료 이벤트 설정
            try:
                from app.bot.trading_bot import shutdown_event
                shutdown_event.set()
                self.logger.warning("전역 종료 이벤트 설정됨")
            except ImportError:
                self.logger.warning("shutdown_event를 찾을 수 없습니다. 개별 스레드만 중지합니다.")
            
            with lock:
                # 모든 사용자의 모든 스레드 중지
                user_ids = list(trading_bots.keys())
                for user_id in user_ids:
                    user_results = self.stop_user_threads(user_id, force)
                    results.extend(user_results)
                
                # 강제 중지인 경우 모든 데이터 삭제
                if force:
                    trading_bots.clear()
                    self.logger.warning("모든 거래봇 데이터 강제 삭제됨")
                
                self.logger.warning(f"모든 스레드 중지 완료: {len(results)}개")
                
        except Exception as e:
            error_msg = f"전체 스레드 중지 중 오류: {str(e)}"
            self.logger.error(error_msg)
            results.append(ThreadStopResult(
                success=False,
                message=error_msg,
                stop_time=datetime.now()
            ))
        
        return results

    def _serialize_settings(self, settings):
        """설정 객체를 JSON 직렬화 가능한 형태로 변환"""
        try:
            if not settings:
                return {}

            # WTForms 객체인 경우 데이터 추출
            if hasattr(settings, '__dict__') and (hasattr(settings, '_formdata') or hasattr(settings, '_fields')):
                # WTForms 객체로 추정됨
                safe_settings = {}

                # WTForms 객체의 경우 _fields 속성에서 필드 정보 추출
                if hasattr(settings, '_fields'):
                    for field_name, field_obj in settings._fields.items():
                        try:
                            if hasattr(field_obj, 'data'):
                                safe_settings[field_name] = field_obj.data
                        except Exception:
                            safe_settings[field_name] = "N/A"
                    return safe_settings

                # 일반적인 속성 기반 추출
                for attr_name in dir(settings):
                    if not attr_name.startswith('_') and not callable(getattr(settings, attr_name)):
                        try:
                            attr_value = getattr(settings, attr_name)
                            # WTForms Field 객체인 경우 data 추출
                            if hasattr(attr_value, 'data'):
                                safe_settings[attr_name] = attr_value.data
                            elif isinstance(attr_value, (str, int, float, bool, type(None))):
                                safe_settings[attr_name] = attr_value
                        except Exception:
                            continue
                return safe_settings

            # 일반 딕셔너리인 경우
            elif isinstance(settings, dict):
                safe_settings = {}
                for key, value in settings.items():
                    try:
                        # WTForms Field 객체인 경우 data 추출
                        if hasattr(value, 'data'):
                            safe_settings[key] = value.data
                        elif isinstance(value, (str, int, float, bool, type(None), list)):
                            safe_settings[key] = value
                        else:
                            # 직렬화할 수 없는 객체는 문자열로 변환
                            safe_settings[key] = str(value)
                    except Exception:
                        safe_settings[key] = "N/A"
                return safe_settings

            # 기타 객체인 경우 문자열로 변환
            else:
                return {"raw_data": str(settings)}

        except Exception as e:
            self.logger.warning(f"설정 직렬화 중 오류: {str(e)}")
            return {"error": "설정 데이터를 읽을 수 없습니다"}
    
    def get_thread_status(self, user_id: Optional[int] = None, ticker: Optional[str] = None) -> Dict:
        """스레드 상태 조회"""
        status = {
            "total_threads": 0,
            "running_threads": 0,
            "stopped_threads": 0,
            "threads": []
        }

        try:
            with lock:
                # print(f"trading_bots: {trading_bots.items()}")
                for uid, user_bots in trading_bots.items():
                    # 특정 사용자만 조회하는 경우
                    if user_id is not None and uid != user_id:
                        continue

                    for tick, bot_info in user_bots.items():
                        # 특정 티커만 조회하는 경우
                        if ticker is not None and tick != ticker:
                            continue

                        is_running = bot_info.get("running", False)
                        thread_id = bot_info.get("thread_id")
                        strategy = bot_info.get("strategy")
                        interval_label = bot_info.get("interval_label")
                        username = bot_info.get("username")

                        # settings 안전하게 처리 (WTForms 객체 처리)
                        raw_settings = bot_info.get("settings", {})
                        safe_settings = self._serialize_settings(raw_settings)
                        # print(f"safe_settings: {safe_settings}")

                        thread_data = {
                            "user_id": uid,
                            "ticker": tick,
                            "thread_id": thread_id,
                            "running": is_running,
                            "settings": safe_settings,
                            "start_time": bot_info.get("start_time"),
                            "stop_requested": self.stop_requests.get(f"{uid}_{tick}", False),
                            "strategy": strategy,
                            "interval_label": interval_label,
                            "username" : username
                        }

                        status["threads"].append(thread_data)
                        status["total_threads"] += 1

                        if is_running:
                            status["running_threads"] += 1
                        else:
                            status["stopped_threads"] += 1

        except Exception as e:
            self.logger.error(f"스레드 상태 조회 중 오류: {str(e)}")

        return status
    
    def restart_thread(self, user_id: int, ticker: str) -> ThreadStopResult:
        """스레드 재시작 (중지 후 다시 시작)"""
        try:
            # 먼저 기존 스레드 중지
            stop_result = self.stop_specific_thread(user_id, ticker, force=True)
            
            if not stop_result.success:
                return stop_result
            
            # TODO: 여기서 새 스레드 시작 로직 호출
            # 실제 구현 시에는 거래봇 시작 함수를 호출해야 함
            self.logger.info(f"스레드 재시작 준비 완료: User {user_id}, Ticker {ticker}")
            
            return ThreadStopResult(
                success=True,
                user_id=user_id,
                ticker=ticker,
                message=f"스레드 재시작 준비 완료: {ticker}",
                stop_time=datetime.now()
            )
            
        except Exception as e:
            error_msg = f"스레드 재시작 중 오류: {str(e)}"
            self.logger.error(error_msg)
            return ThreadStopResult(
                success=False,
                user_id=user_id,
                ticker=ticker,
                message=error_msg,
                stop_time=datetime.now()
            )
    
    def get_stop_history(self, limit: int = 50) -> List[Dict]:
        """스레드 중지 이력 조회"""
        try:
            # 최근 이력부터 반환
            recent_history = self.stop_history[-limit:] if len(self.stop_history) > limit else self.stop_history
            
            return [
                {
                    "success": result.success,
                    "thread_id": result.thread_id,
                    "user_id": result.user_id,
                    "ticker": result.ticker,
                    "message": result.message,
                    "stop_time": result.stop_time.isoformat() if result.stop_time else None
                }
                for result in reversed(recent_history)  # 최신순으로 정렬
            ]
            
        except Exception as e:
            self.logger.error(f"중지 이력 조회 중 오류: {str(e)}")
            return []
    
    def emergency_stop(self) -> List[ThreadStopResult]:
        """긴급 중지 (모든 스레드를 강제로 즉시 중지)"""
        self.logger.critical("긴급 중지 실행됨!")
        
        try:
            # 전역 종료 이벤트 설정
            try:
                from app.bot.trading_bot import shutdown_event
                shutdown_event.set()
            except ImportError:
                pass
            
            # 모든 스레드 강제 중지
            results = self.stop_all_threads(force=True)
            
            # 추가 정리 작업
            self.stop_requests.clear()
            
            self.logger.critical(f"긴급 중지 완료: {len(results)}개 스레드 처리됨")
            return results
            
        except Exception as e:
            error_msg = f"긴급 중지 중 오류: {str(e)}"
            self.logger.critical(error_msg)
            return [ThreadStopResult(
                success=False,
                message=error_msg,
                stop_time=datetime.now()
            )]




# 전역 스레드 컨트롤러 인스턴스
thread_controller = ThreadController()

# 편의 함수들
def stop_thread(user_id: int, ticker: str, force: bool = False) -> ThreadStopResult:
    """특정 스레드 중지"""
    return thread_controller.stop_specific_thread(user_id, ticker, force)

def stop_user_threads(user_id: int, force: bool = False) -> List[ThreadStopResult]:
    """사용자의 모든 스레드 중지"""
    return thread_controller.stop_user_threads(user_id, force)

def stop_all_threads(force: bool = False) -> List[ThreadStopResult]:
    """모든 스레드 중지"""
    return thread_controller.stop_all_threads(force)

def emergency_stop() -> List[ThreadStopResult]:
    """긴급 중지"""
    return thread_controller.emergency_stop()

def get_thread_status(user_id: Optional[int] = None, ticker: Optional[str] = None) -> Dict:
    """스레드 상태 조회"""
    return thread_controller.get_thread_status(user_id, ticker)
