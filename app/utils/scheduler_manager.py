"""
APScheduler를 이용한 트레이딩 봇 스케줄링 관리
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import logging
import threading
from datetime import datetime


class TradingSchedulerManager:
    """트레이딩 봇 스케줄러 관리 클래스"""

    def __init__(self):
        self.scheduler = None
        self.active_jobs = {}  # {job_id: job_info}
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self._is_started = False
        self._setup_scheduler()

    def _setup_scheduler(self):
        """스케줄러 초기 설정"""
        job_stores = {
            'default': MemoryJobStore()
        }

        executors = {
            'default': ThreadPoolExecutor(max_workers=10)
        }

        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 60
        }

        self.scheduler = BackgroundScheduler(
            jobstores=job_stores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='Asia/Seoul'
        )

        # 이벤트 리스너 추가
        self.scheduler.add_listener(self._job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    def _job_listener(self, event):
        """작업 실행 이벤트 리스너"""
        if event.exception:
            self.logger.error(f"Job {event.job_id} crashed: {event.exception}")
        else:
            self.logger.info(f"Job {event.job_id} executed successfully")
            # 작업 실행 정보 업데이트
            with self.lock:
                if event.job_id in self.active_jobs:
                    self.active_jobs[event.job_id]['last_run'] = datetime.now()
                    if 'run_count' not in self.active_jobs[event.job_id]:
                        self.active_jobs[event.job_id]['run_count'] = 0
                    self.active_jobs[event.job_id]['run_count'] += 1
                    self.logger.info(f"Job {event.job_id} run count: {self.active_jobs[event.job_id]['run_count']}")

    def is_started(self):
        """스케줄러가 시작되었는지 확인"""
        return self._is_started and self.scheduler is not None and self.scheduler.running

    def start(self):
        """스케줄러 시작"""
        if not self._is_started:
            try:
                self.scheduler.start()
                self._is_started = True
                self.logger.info("트레이딩 스케줄러가 시작되었습니다.")
            except Exception as e:
                self.logger.error(f"스케줄러 시작 실패: {e}")
                self._is_started = False

    def shutdown(self):
        """스케줄러 종료"""
        if self._is_started and self.scheduler and self.scheduler.running:
            try:
                self.scheduler.shutdown(wait=False)
                self._is_started = False
                self.logger.info("트레이딩 스케줄러가 종료되었습니다.")
            except Exception as e:
                self.logger.error(f"스케줄러 종료 실패: {e}")

    def add_trading_job(self, job_id, trading_func, interval_seconds, user_id, ticker, strategy):
        """트레이딩 작업 추가"""
        with self.lock:
            try:
                # 스케줄러가 시작되지 않았으면 시작
                if not self.is_started():
                    self.start()

                # 기존 작업이 있으면 제거
                if job_id in self.active_jobs:
                    self.remove_job(job_id)

                # 새 작업 추가
                job = self.scheduler.add_job(
                    func=trading_func,
                    trigger='interval',
                    seconds=interval_seconds,
                    id=job_id,
                    replace_existing=True,
                    next_run_time=datetime.now()
                )

                # 작업 정보 저장
                self.active_jobs[job_id] = {
                    'job': job,
                    'user_id': user_id,
                    'ticker': ticker,
                    'strategy': strategy,
                    'interval': interval_seconds,
                    'created_at': datetime.now(),
                    'last_run': None,
                    'run_count': 0
                }

                self.logger.info(f"트레이딩 작업 추가: {job_id} (간격: {interval_seconds}초)")

                # 다음 실행 시간 로깅
                next_run = job.next_run_time
                self.logger.info(f"다음 실행 시간: {next_run}")

                return True

            except Exception as e:
                self.logger.error(f"트레이딩 작업 추가 실패: {e}")
                return False

    def remove_job(self, job_id):
        """작업 제거"""
        with self.lock:
            try:
                if job_id in self.active_jobs:
                    self.scheduler.remove_job(job_id)
                    del self.active_jobs[job_id]
                    self.logger.info(f"트레이딩 작업 제거: {job_id}")
                    return True
                return False
            except Exception as e:
                self.logger.error(f"트레이딩 작업 제거 실패: {e}")
                return False

    def get_job_info(self, job_id):
        """작업 정보 조회"""
        with self.lock:
            return self.active_jobs.get(job_id)

    def get_all_jobs(self):
        """모든 작업 정보 조회"""
        with self.lock:
            return dict(self.active_jobs)

    def get_user_jobs(self, user_id):
        """특정 사용자의 작업 목록 조회"""
        with self.lock:
            return {job_id: info for job_id, info in self.active_jobs.items()
                    if info['user_id'] == user_id}

    def pause_job(self, job_id):
        """작업 일시 정지"""
        try:
            self.scheduler.pause_job(job_id)
            self.logger.info(f"작업 일시 정지: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"작업 일시 정지 실패: {e}")
            return False

    def resume_job(self, job_id):
        """작업 재개"""
        try:
            self.scheduler.resume_job(job_id)
            self.logger.info(f"작업 재개: {job_id}")
            return True
        except Exception as e:
            self.logger.error(f"작업 재개 실패: {e}")
            return False

    def get_status(self):
        """스케줄러 상태 정보 반환"""
        with self.lock:
            job_details = {}
            for job_id, job_info in self.active_jobs.items():
                job_details[job_id] = {
                    'user_id': job_info['user_id'],
                    'ticker': job_info['ticker'],
                    'strategy': job_info['strategy'],
                    'interval': job_info['interval'],
                    'created_at': job_info['created_at'].isoformat(),
                    'last_run': job_info['last_run'].isoformat() if job_info['last_run'] else None,
                    'run_count': job_info['run_count']
                }

            return {
                'scheduler_running': self.is_started(),
                'active_jobs_count': len(self.active_jobs),
                'job_details': job_details,
                'scheduler_state': self.scheduler.state if self.scheduler else None
            }


# 글로벌 스케줄러 인스턴스
scheduler_manager = TradingSchedulerManager()