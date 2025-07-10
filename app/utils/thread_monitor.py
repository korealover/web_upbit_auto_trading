# app/utils/thread_monitor.py
import threading
import time
import logging
import os
import json
import sys
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from contextlib import contextmanager


@dataclass
class ThreadInfo:
    """스레드 정보 데이터 클래스"""
    thread_id: int
    name: str
    is_alive: bool
    daemon: bool
    start_time: datetime
    status: str = "unknown"
    user_id: Optional[int] = None
    ticker: Optional[str] = None
    strategy: Optional[str] = None


@dataclass
class ThreadPoolStats:
    """스레드풀 통계 데이터 클래스"""
    total_threads: int
    active_threads: int
    daemon_threads: int
    trading_bot_threads: int
    system_threads: int
    total_cpu_percent: float
    total_memory_mb: float
    avg_thread_age_seconds: float
    oldest_thread_age_seconds: float
    timestamp: datetime


class DateTimeEncoder(json.JSONEncoder):
    """datetime 객체를 JSON 직렬화 가능한 문자열로 변환하는 커스텀 인코더"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class ThreadPoolMonitor:
    """간단한 스레드풀 모니터링 클래스"""

    def __init__(self):
        self.thread_registry: Dict[int, ThreadInfo] = {}
        self.alerts: List[Dict] = []
        self.logger = logging.getLogger(__name__)

        # 기본 임계값
        self.max_threads_threshold = 50
        self.max_cpu_threshold = 80.0
        self.max_memory_threshold = 500.0
        self.max_thread_age_threshold = 3600

    def register_thread(self, user_id: Optional[int] = None,
                        ticker: Optional[str] = None,
                        strategy: Optional[str] = None):
        """현재 스레드를 등록"""
        current_thread = threading.current_thread()
        thread_info = ThreadInfo(
            thread_id=current_thread.ident,
            name=current_thread.name,
            is_alive=current_thread.is_alive(),
            daemon=current_thread.daemon,
            start_time=datetime.now(),
            user_id=user_id,
            ticker=ticker,
            strategy=strategy
        )

        self.thread_registry[current_thread.ident] = thread_info
        self.logger.debug(f"스레드 등록: {current_thread.name} (ID: {current_thread.ident})")

    def unregister_thread(self, thread_id: Optional[int] = None):
        """스레드 등록 해제"""
        if thread_id is None:
            thread_id = threading.current_thread().ident

        if thread_id in self.thread_registry:
            thread_info = self.thread_registry.pop(thread_id)
            self.logger.debug(f"스레드 등록 해제: {thread_info.name} (ID: {thread_id})")

    @contextmanager
    def monitor_thread_context(self, user_id: Optional[int] = None,
                               ticker: Optional[str] = None,
                               strategy: Optional[str] = None):
        """컨텍스트 매니저로 스레드 모니터링"""
        self.register_thread(user_id, ticker, strategy)
        try:
            yield
        finally:
            self.unregister_thread()

    def collect_stats(self) -> ThreadPoolStats:
        """현재 스레드풀 통계 수집"""
        all_threads = threading.enumerate()
        current_time = datetime.now()

        # 기본 통계
        total_threads = len(all_threads)    # 전체 스레드
        active_threads = sum(1 for t in all_threads if t.is_alive())
        daemon_threads = sum(1 for t in all_threads if t.daemon)

        # 거래봇 스레드 카운트
        trading_bot_threads = sum(
            1 for t in all_threads
            if 'trading' in t.name.lower() or 'bot' in t.name.lower()
        )

        system_threads = total_threads - trading_bot_threads

        # CPU 및 메모리 사용량 (psutil 없이 기본값)
        try:
            import psutil
            process = psutil.Process()

            # CPU 사용률 측정 - 첫 번째 호출 후 짧은 간격을 두고 재측정
            process.cpu_percent()  # 첫 번째 호출 (기준점 설정)
            import time
            time.sleep(0.1)  # 100ms 대기
            total_cpu_percent = process.cpu_percent()
            # 메모리 사용량 (MB 단위)
            total_memory_mb = process.memory_info().rss / 1024 / 1024

        except ImportError:
            total_cpu_percent = 0.0
            total_memory_mb = 0.0
        except Exception as e:
            # psutil이 있지만 다른 오류가 발생한 경우
            print(f"시스템 모니터링 오류: {e}")

        # 스레드 수명 계산
        thread_ages = []
        for thread_id, thread_info in self.thread_registry.items():
            age = (current_time - thread_info.start_time).total_seconds()
            thread_ages.append(age)

        avg_thread_age = sum(thread_ages) / len(thread_ages) if thread_ages else 0
        oldest_thread_age = max(thread_ages) if thread_ages else 0

        return ThreadPoolStats(
            total_threads=total_threads,
            active_threads=active_threads,
            daemon_threads=daemon_threads,
            trading_bot_threads=trading_bot_threads,
            system_threads=system_threads,
            total_cpu_percent=total_cpu_percent,
            total_memory_mb=total_memory_mb,
            avg_thread_age_seconds=avg_thread_age,
            oldest_thread_age_seconds=oldest_thread_age,
            timestamp=current_time
        )

    def get_thread_details(self) -> List[Dict]:
        """상세 스레드 정보 반환"""
        all_threads = threading.enumerate()
        thread_details = []

        for thread in all_threads:
            thread_info = self.thread_registry.get(thread.ident, None)

            detail = {
                'id': thread.ident,
                'name': thread.name,
                'is_alive': thread.is_alive(),
                'daemon': thread.daemon,
                'start_time': thread_info.start_time.isoformat() if thread_info else None,
                'user_id': thread_info.user_id if thread_info else None,
                'ticker': thread_info.ticker if thread_info else None,
                'strategy': thread_info.strategy if thread_info else None,
                'age_seconds': (
                    (datetime.now() - thread_info.start_time).total_seconds()
                    if thread_info else None
                )
            }
            thread_details.append(detail)

        return thread_details

    def _cleanup_dead_threads(self):
        """죽은 스레드 정리"""
        alive_thread_ids = {t.ident for t in threading.enumerate()}
        dead_thread_ids = [
            tid for tid in self.thread_registry.keys()
            if tid not in alive_thread_ids
        ]

        for tid in dead_thread_ids:
            self.unregister_thread(tid)

    def force_garbage_collection(self):
        """강제 가비지 컬렉션"""
        import gc
        before_objects = len(gc.get_objects())
        collected = gc.collect()
        after_objects = len(gc.get_objects())

        self.logger.info(
            f"가비지 컬렉션 완료: {collected}개 수집, "
            f"객체 수 {before_objects} -> {after_objects}"
        )

        return {
            'collected_objects': collected,
            'before_objects': before_objects,
            'after_objects': after_objects
        }

    def export_stats(self, filepath: str) -> None:
        """통계 데이터를 JSON 파일로 내보내기"""
        try:
            # 디렉토리 생성
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            # 현재 통계 수집
            stats = self.collect_stats()
            thread_details = self.get_thread_details()

            # 내보낼 데이터 구성
            export_data = {
                'export_info': {
                    'timestamp': datetime.now().isoformat(),
                    'version': '1.0',
                    'description': '스레드풀 모니터링 통계 데이터'
                },
                'stats': asdict(stats),
                'thread_details': thread_details,
                'alerts': self.alerts.copy(),
                'system_info': {
                    'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                    'thread_count': threading.active_count()
                }
            }

            # stats 딕셔너리의 timestamp를 문자열로 변환
            if 'timestamp' in export_data['stats']:
                export_data['stats']['timestamp'] = export_data['stats']['timestamp'].isoformat()

            # psutil 사용 가능한 경우에만 추가 정보 수집
            try:
                import psutil
                export_data['system_info'].update({
                    'cpu_count': psutil.cpu_count(),
                    'memory_total_mb': psutil.virtual_memory().total / (1024 * 1024)
                })
            except ImportError:
                self.logger.warning("psutil이 설치되지 않아 시스템 정보를 수집할 수 없습니다.")

            # JSON 파일로 저장 (커스텀 인코더 사용)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, cls=DateTimeEncoder, ensure_ascii=False, indent=2)

            self.logger.info(f"통계 데이터를 성공적으로 내보냈습니다: {filepath}")

        except Exception as e:
            self.logger.error(f"통계 데이터 내보내기 실패: {str(e)}")
            raise


# 전역 모니터 인스턴스
thread_monitor = ThreadPoolMonitor()


# 데코레이터
def monitor_trading_thread(user_id: int = None, ticker: str = None, strategy: str = None):
    """거래 스레드 모니터링 데코레이터"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            with thread_monitor.monitor_thread_context(user_id, ticker, strategy):
                return func(*args, **kwargs)

        return wrapper

    return decorator