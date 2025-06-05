import os
import logging
from datetime import datetime, timedelta


def setup_logger(ticker, log_level=logging.INFO, log_rotation_days=7):
    """로깅 설정 함수 (로그 파일 로테이션 추가)"""
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
    logger = logging.getLogger(ticker)

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