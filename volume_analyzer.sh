#!/bin/bash

# 거래량 분석기 데몬 스크립트
# 사용법: ./volume_analyzer.sh {start|stop|status|restart|analyze}

# 설정 변수
SCRIPT_PATH="/home/korealover/web_upbit_auto_trading" # 스크립트 경로
PYTHON_SCRIPT="$SCRIPT_PATH/volume_analyzer.py"  # 실행할 파이썬 스크립트 경로
PID_FILE="$SCRIPT_PATH/volume_analyzer.pid"      # PID 파일 경로
LOG_FILE="$SCRIPT_PATH/logs/volume_analyzer_daemon.log"  # 로그 파일 경로
PYTHON_CMD="/home/korealover/web_upbit_auto_trading/.venv/bin/python3"  # 파이썬 명령어

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

# 정기 분석 스케줄러 시작
start() {
    if is_running; then
        log "거래량 분석기가 이미 실행 중입니다. PID: $(cat "$PID_FILE")"
        return 1
    fi

    log "거래량 분석기 스케줄러를 시작합니다..."

    # 로그 디렉토리 생성
    mkdir -p "$SCRIPT_PATH/logs"

    # 백그라운드로 실행 (정기 분석 모드)
    # Python 스크립트에 자동으로 옵션 2를 전달
    echo "2" | nohup "$PYTHON_CMD" "$PYTHON_SCRIPT" > "$SCRIPT_PATH/logs/volume_analyzer_output.log" 2>&1 &

    # PID 저장
    echo $! > "$PID_FILE"

    # 실행 확인
    sleep 3
    if is_running; then
        log "거래량 분석기 스케줄러가 성공적으로 시작되었습니다. PID: $(cat "$PID_FILE")"
        log "분석 시간: 매일 09:00, 15:00, 21:00"
        return 0
    else
        log "거래량 분석기 스케줄러 시작에 실패했습니다."
        return 1
    fi
}

# 스크립트 중지
stop() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        log "거래량 분석기를 중지합니다. PID: $PID"

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

        log "거래량 분석기가 중지되었습니다."
        return 0
    else
        log "거래량 분석기가 실행 중이 아닙니다."
        return 1
    fi
}

# 스크립트 상태 확인
status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        log "거래량 분석기가 실행 중입니다. PID: $PID"

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
        LOG_COUNT=$(ls -l "$SCRIPT_PATH/logs/" 2>/dev/null | grep -c "volume_analyzer" || echo "0")
        log "로그 파일 수: $LOG_COUNT"

        # 다음 분석 시간 표시
        current_hour=$(date +%H)
        if [ "$current_hour" -lt 8 ]; then
            log "다음 분석 시간: 오늘 08:00"
        elif [ "$current_hour" -lt 12 ]; then
            log "다음 분석 시간: 오늘 12:00"
        elif [ "$current_hour" -lt 17 ]; then
            log "다음 분석 시간: 오늘 17:00"
        elif [ "$current_hour" -lt 21 ]; then
            log "다음 분석 시간: 오늘 21:00"
        else
            log "다음 분석 시간: 내일 08:00"
        fi

        return 0
    else
        log "거래량 분석기가 실행 중이 아닙니다."
        return 1
    fi
}

# 스크립트 재시작
restart() {
    log "거래량 분석기를 재시작합니다..."
    stop
    sleep 3
    start
}

# 즉시 분석 실행 (백그라운드 스케줄러와 별도)
analyze() {
    log "즉시 거래량 분석을 실행합니다..."

    # 로그 디렉토리 생성
    mkdir -p "$SCRIPT_PATH/logs"

    # 즉시 분석 실행 (옵션 1)
    echo "1" | "$PYTHON_CMD" "$PYTHON_SCRIPT" >> "$SCRIPT_PATH/logs/volume_analyzer_manual.log" 2>&1

    if [ $? -eq 0 ]; then
        log "거래량 분석이 성공적으로 완료되었습니다."
        log "결과는 텔레그램으로 전송되었습니다."
        return 0
    else
        log "거래량 분석 실행 중 오류가 발생했습니다."
        return 1
    fi
}

# 로그 파일 확인
logs() {
    log "최근 로그 파일들:"
    if [ -f "$LOG_FILE" ]; then
        echo "=== 데몬 로그 (최근 20줄) ==="
        tail -20 "$LOG_FILE"
        echo ""
    fi

    if [ -f "$SCRIPT_PATH/logs/volume_analyzer_output.log" ]; then
        echo "=== 분석기 출력 로그 (최근 20줄) ==="
        tail -20 "$SCRIPT_PATH/logs/volume_analyzer_output.log"
        echo ""
    fi

    if [ -f "$SCRIPT_PATH/logs/volume_analyzer.log" ]; then
        echo "=== 분석기 로그 (최근 20줄) ==="
        tail -20 "$SCRIPT_PATH/logs/volume_analyzer.log"
    fi
}

# 도움말 표시
help() {
    echo "거래량 분석기 관리 스크립트"
    echo "사용법: $0 {start|stop|status|restart|analyze|logs|help}"
    echo ""
    echo "명령어 설명:"
    echo "  start    - 정기 분석 스케줄러 시작 (매일 9시, 15시, 21시)"
    echo "  stop     - 정기 분석 스케줄러 중지"
    echo "  status   - 현재 상태 및 다음 분석 시간 확인"
    echo "  restart  - 정기 분석 스케줄러 재시작"
    echo "  analyze  - 즉시 분석 실행 (스케줄러와 별도)"
    echo "  logs     - 최근 로그 파일 내용 확인"
    echo "  help     - 이 도움말 표시"
    echo ""
    echo "예시:"
    echo "  $0 start     # 정기 분석 스케줄러 시작"
    echo "  $0 analyze   # 지금 바로 분석 실행"
    echo "  $0 status    # 현재 상태 확인"
    echo "  $0 logs      # 로그 확인"
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
    analyze)
        analyze
        ;;
    logs)
        logs
        ;;
    help)
        help
        ;;
    *)
        echo "사용법: $0 {start|stop|status|restart|analyze|logs|help}"
        echo "자세한 사용법은 '$0 help'를 입력하세요."
        exit 1
        ;;
esac

exit $?