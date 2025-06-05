import os
import logging
from datetime import datetime, timedelta

# 로거 캐시 및 마지막 업데이트 시간 저장
logger_cache = {}
logger_date_cache = {}

def setup_logger(ticker, log_level=logging.INFO, log_rotation_days=7):
    """로깅 설정 함수 (로그 파일 로테이션 추가)"""
    global logger_cache, logger_date_cache

    # 오늘 날짜 가져오기
    today = datetime.now().strftime('%Y%m%d')

    # 캐시된 로거가 있고 날짜가 같으면 기존 로거 반환
    if ticker in logger_cache and logger_date_cache.get(ticker) == today:
        return logger_cache[ticker]

    # 로그 디렉토리가 없으면 생성
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 로그 파일명 생성 (날짜_코인명.log)
    ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
    log_filename = os.path.join(log_dir, f"{datetime.now().strftime('%Y%m%d')}_{ticker_symbol}.log")

    # 이전 로그 파일 정리 (X일 이상 지난 파일)
    cleanup_old_logs(log_dir, days=log_rotation_days)

    # 로거 설정
    logger = logging.getLogger(f"{ticker}_{today}")

    # 이미 핸들러가 설정되어 있으면 제거
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)

    logger.setLevel(log_level)

    # 파일 핸들러 추가
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(log_level)

    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # 포맷 설정
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # 핸들러 추가
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # 로깅이 중복되지 않도록 propagate 속성 비활성화
    logger.propagate = False

    # 로거와 날짜 정보 캐시에 저장
    logger_cache[ticker] = logger
    logger_date_cache[ticker] = today

    return logger


def cleanup_old_logs(log_dir, days=7):
    """오래된 로그 파일 정리"""
    if not os.path.exists(log_dir):
        return

    current_time = datetime.now()
    cutoff_time = current_time - timedelta(days=days)

    for filename in os.listdir(log_dir):
        file_path = os.path.join(log_dir, filename)

        # 파일의 수정 시간 확인
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))

        # 설정된 일수보다 오래된 파일 삭제
        if file_mod_time < cutoff_time:
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"오래된 로그 파일 삭제 중 오류: {e}")


def get_logger_with_current_date(ticker, log_level=logging.INFO, log_rotation_days=7):
    """현재 날짜로 로거 가져오기 (날짜 변경 시 자동 업데이트)"""
    today = datetime.now().strftime('%Y%m%d')

    # 캐시된 로거가 있는지 확인하고 날짜가 다르면 새로 생성
    if ticker not in logger_cache or logger_date_cache.get(ticker) != today:
        return setup_logger(ticker, log_level, log_rotation_days)

    return logger_cache[ticker]
