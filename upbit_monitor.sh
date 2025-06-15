#!/bin/bash

# 코인 모니터링 데몬 스크립트
# 사용법: ./coin_monitor.sh {start|stop|status|restart}

# 설정 변수
SCRIPT_PATH="/home/korealover/web_upbit_auto_trading" # 스크립트 경로
PYTHON_SCRIPT="$SCRIPT_PATH/coin_monitor.py"  # 실행할 파이썬 스크립트 경로
PID_FILE="$SCRIPT_PATH/coin_monitor.pid"      # PID 파일 경로
LOG_FILE="$SCRIPT_PATH/logs/coin_monitor_daemon.log"  # 로그 파일 경로
PYTHON_CMD="/home/korealover/web_upbit_auto_trading/.venv/bin/python3"                         # 파이썬 명령어 (환경에 따라 python 또는 python3)

# 현재 날짜 및 시간 얻기
get_datetime() {
    date "+%Y-%m-%d %H:%M:%S"
}

# 로그 기록 함수
log() {
    echo "$(get_datetime) - $1" >> "$LOG_FILE"
    echo "$1"
}

# 스크립트가 실행 중인지 확인
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 실행 중
        else
            # PID 파일은 있지만 프로세스가 없는 경우
            rm -f "$PID_FILE"
        fi
    fi
    return 1  # 실행 중이 아님
}

# 스크립트 시작
start() {
    if is_running; then
        log "코인 모니터링이 이미 실행 중입니다. PID: $(cat "$PID_FILE")"
        return 1
    fi

    log "코인 모니터링을 시작합니다..."

    # 로그 디렉토리 생성
    mkdir -p "$SCRIPT_PATH/logs"

    # 백그라운드로 실행
    nohup "$PYTHON_CMD" "$PYTHON_SCRIPT" > "$SCRIPT_PATH/logs/coin_monitor_output.log" 2>&1 &

    # PID 저장
    echo $! > "$PID_FILE"

    # 실행 확인
    sleep 2
    if is_running; then
        log "코인 모니터링이 성공적으로 시작되었습니다. PID: $(cat "$PID_FILE")"
        return 0
    else
        log "코인 모니터링 시작에 실패했습니다."
        return 1
    fi
}

# 스크립트 중지
stop() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        log "코인 모니터링을 중지합니다. PID: $PID"

        # 프로세스 종료
        kill -15 "$PID"

        # 정상 종료 대기
        sleep 5

        # 여전히 실행 중이면 강제 종료
        if ps -p "$PID" > /dev/null 2>&1; then
            log "정상 종료에 실패했습니다. 강제 종료합니다."
            kill -9 "$PID"
            sleep 2
        fi

        # PID 파일 제거
        rm -f "$PID_FILE"

        log "코인 모니터링이 중지되었습니다."
        return 0
    else
        log "코인 모니터링이 실행 중이 아닙니다."
        return 1
    fi
}

# 스크립트 상태 확인
status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        log "코인 모니터링이 실행 중입니다. PID: $PID"

        # 실행 시간 확인
        if [ "$(uname)" == "Darwin" ]; then
            # macOS
            STARTED=$(ps -p "$PID" -o lstart= 2>/dev/null)
        else
            # Linux
            STARTED=$(ps -p "$PID" -o lstart= 2>/dev/null)
        fi

        log "실행 시간: $STARTED"

        # 메모리 사용량 확인
        if [ "$(uname)" == "Darwin" ]; then
            # macOS
            MEM=$(ps -p "$PID" -o rss= 2>/dev/null | awk '{print $1/1024 " MB"}')
        else
            # Linux
            MEM=$(ps -p "$PID" -o rss= 2>/dev/null | awk '{print $1/1024 " MB"}')
        fi

        log "메모리 사용량: $MEM"

        # 로그 파일 확인
        LOG_COUNT=$(ls -l "$SCRIPT_PATH/logs/" | grep -c "coin_monitor_")
        log "로그 파일 수: $LOG_COUNT"

        return 0
    else
        log "코인 모니터링이 실행 중이 아닙니다."
        return 1
    fi
}

# 스크립트 재시작
restart() {
    log "코인 모니터링을 재시작합니다..."
    stop
    sleep 2
    start
}

# 메인 로직
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    restart)
        restart
        ;;
    *)
        echo "사용법: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac

exit $?