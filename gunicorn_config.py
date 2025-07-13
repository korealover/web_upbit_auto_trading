# gunicorn_config.py
import multiprocessing
import os
from app.utils.scheduler_manager import scheduler_manager

# 기본 설정
bind = "0.0.0.0:5000"
workers = 1  # 중요: 스케줄러를 위해 단일 워커 사용
worker_class = "eventlet"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 30
keepalive = 2
preload_app = True  # 중요: 앱 프리로드 활성화

# 로깅 설정
accesslog = "/logs/gunicorn_access.log"
errorlog = "/logs/gunicorn_error.log"
loglevel = "info"

# 데몬 설정
daemon = False
pidfile = "gunicorn.pid"

# 스케줄러 관리 함수들
def when_ready(server):
    """Gunicorn 서버가 준비되면 스케줄러 시작"""
    try:
        scheduler_manager.start()
        server.log.info("APScheduler 시작됨 (Gunicorn)")
    except Exception as e:
        server.log.error(f"스케줄러 시작 실패: {e}")

def on_exit(server):
    """Gunicorn 서버 종료 시 스케줄러 정리"""
    try:
        scheduler_manager.shutdown()
        server.log.info("APScheduler 종료됨 (Gunicorn)")
    except Exception as e:
        server.log.error(f"스케줄러 종료 실패: {e}")

def worker_exit(server, worker):
    """워커 종료 시 호출"""
    server.log.info(f"워커 {worker.pid} 종료됨")

def pre_fork(server, worker):
    """워커 포크 전 호출"""
    server.log.info(f"워커 {worker.pid} 포크 준비")

def post_fork(server, worker):
    """워커 포크 후 호출"""
    server.log.info(f"워커 {worker.pid} 포크 완료")