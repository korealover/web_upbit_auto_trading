
from flask_socketio import emit, join_room, leave_room, disconnect
from flask import request
from flask_login import current_user
import logging
import os
import time
from datetime import datetime, timedelta
from threading import Thread
import html

logger = logging.getLogger(__name__)

# 활성 연결된 클라이언트 추적
active_connections = {}
log_watchers = {}


def register_socketio_handlers(socketio):
    @socketio.on('connect')
    def handle_connect():
        if not current_user.is_authenticated:
            logger.warning("인증되지 않은 사용자의 WebSocket 연결 시도")
            disconnect()
            return False

        user_id = current_user.id
        session_id = request.sid

        # 활성 연결 추가
        active_connections[session_id] = {
            'user_id': user_id,
            'connected_at': datetime.now(),
            'subscribed_ticker': None
        }

        logger.info(f"사용자 {user_id}가 WebSocket에 연결됨 (세션: {session_id})")
        emit('status', {
            'message': '실시간 로그 스트림에 연결되었습니다.',
            'timestamp': datetime.now().isoformat()
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        session_id = request.sid
        if session_id in active_connections:
            user_id = active_connections[session_id]['user_id']

            # 로그 감시 중지
            stop_log_watching(session_id)

            # 활성 연결 제거
            del active_connections[session_id]

            logger.info(f"사용자 {user_id}가 WebSocket에서 연결 해제됨 (세션: {session_id})")

    @socketio.on('subscribe_logs')
    def handle_subscribe_logs(data):
        if not current_user.is_authenticated:
            return

        session_id = request.sid
        ticker = data.get('ticker', '')  # 빈 문자열이면 전체 로그

        if session_id in active_connections:
            # 기존 구독 중지
            stop_log_watching(session_id)

            # 새 구독 시작
            active_connections[session_id]['subscribed_ticker'] = ticker
            start_log_watching(session_id, ticker, socketio)

            emit('status', {
                'message': f'{"전체" if not ticker else ticker} 로그 구독을 시작했습니다.',
                'timestamp': datetime.now().isoformat()
            })

    @socketio.on('unsubscribe_logs')
    def handle_unsubscribe_logs():
        session_id = request.sid
        if session_id in active_connections:
            stop_log_watching(session_id)
            active_connections[session_id]['subscribed_ticker'] = None

            emit('status', {
                'message': '로그 구독을 중지했습니다.',
                'timestamp': datetime.now().isoformat()
            })

    @socketio.on('request_recent_logs')
    def handle_request_recent_logs(data):
        """최근 로그 요청 처리"""
        if not current_user.is_authenticated:
            return

        ticker = data.get('ticker', '')
        limit = data.get('limit', 50)

        try:
            logs = get_recent_logs(ticker, limit)
            emit('recent_logs', {'logs': logs})
        except Exception as e:
            logger.error(f"최근 로그 요청 처리 중 오류: {e}")
            emit('error', {'message': '로그를 불러오는 중 오류가 발생했습니다.'})


def start_log_watching(session_id, ticker='', socketio=None):
    """특정 세션에 대한 로그 감시 시작"""
    if session_id in log_watchers:
        return  # 이미 감시 중

    def watch_logs():
        log_dir = 'logs'
        last_positions = {}  # 각 로그 파일의 마지막 읽은 위치

        while session_id in active_connections:
            try:
                # 감시할 로그 파일들 결정
                log_files = get_log_files_to_watch(ticker)

                for log_file in log_files:
                    log_path = os.path.join(log_dir, log_file)
                    if not os.path.exists(log_path):
                        continue

                    # 파일 크기 확인
                    current_size = os.path.getsize(log_path)
                    last_position = last_positions.get(log_file, 0)

                    if current_size > last_position:
                        # 새로운 로그 라인 읽기
                        new_lines = read_new_lines(log_path, last_position)

                        for line in new_lines:
                            if line.strip():
                                log_entry = parse_log_line(line.strip())
                                if log_entry and socketio:
                                    socketio.emit('new_log', log_entry, room=session_id)

                        last_positions[log_file] = current_size

                time.sleep(1)  # 1초마다 확인

            except Exception as e:
                logger.error(f"로그 감시 중 오류 (세션 {session_id}): {e}")
                time.sleep(5)  # 오류 시 5초 대기

    # 백그라운드 스레드에서 로그 감시 시작
    watcher_thread = Thread(target=watch_logs, daemon=True)
    log_watchers[session_id] = watcher_thread
    watcher_thread.start()


def stop_log_watching(session_id):
    """특정 세션의 로그 감시 중지"""
    if session_id in log_watchers:
        # 스레드는 daemon이므로 자동으로 종료됨
        del log_watchers[session_id]


def get_log_files_to_watch(ticker=''):
    """감시할 로그 파일 목록 반환"""
    today = datetime.now().strftime('%Y%m%d')

    if ticker:
        # 특정 티커의 로그 파일
        ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
        return [f"{today}_{ticker_symbol}.log"]
    else:
        # 전체 로그 파일
        return [f"{today}_web.log"]


def read_new_lines(file_path, start_position):
    """파일의 특정 위치부터 새로운 라인들 읽기"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            file.seek(start_position)
            return file.readlines()
    except Exception as e:
        logger.error(f"파일 읽기 오류 ({file_path}): {e}")
        return []


def parse_log_line(line):
    """로그 라인 파싱"""
    try:
        parts = line.split(' - ', 2)
        if len(parts) >= 3:
            timestamp, level, message = parts
            return {
                'timestamp': timestamp,
                'level': level,
                'message': html.escape(message),
                'raw_timestamp': datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"로그 라인 파싱 오류: {e}")
    return None


def get_recent_logs(ticker='', limit=50):
    """최근 로그 가져오기 (기존 API 로직 재사용)"""
    log_dir = 'logs'
    logs = []

    try:
        # 로그 파일들 확인
        for days_back in range(4):
            check_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

            if ticker:
                ticker_symbol = ticker.split('-')[1] if '-' in ticker else ticker
                log_filename = f"{check_date}_{ticker_symbol}.log"
            else:
                log_filename = f"{check_date}_web.log"

            log_path = os.path.join(log_dir, log_filename)

            if os.path.exists(log_path):
                # 파일의 마지막 N줄 읽기
                lines = tail_file(log_path, limit // 4)  # 각 파일에서 일정량씩

                for line in lines:
                    log_entry = parse_log_line(line.strip())
                    if log_entry:
                        logs.append(log_entry)

        # 시간순 정렬
        logs.sort(key=lambda x: x['timestamp'], reverse=True)
        return logs[:limit]

    except Exception as e:
        logger.error(f"최근 로그 가져오기 오류: {e}")
        return []


def tail_file(file_path, num_lines):
    """파일의 마지막 N줄 읽기"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            return lines[-num_lines:] if len(lines) > num_lines else lines
    except Exception as e:
        logger.error(f"파일 tail 읽기 오류 ({file_path}): {e}")
        return []