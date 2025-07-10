import signal
import sys
import eventlet
from app import create_app, socketio
from app.routes import stop_all_bots  # 봇 종료 함수
import threading  # 수정: 표준 라이브러리에서 직접 임포트

eventlet.monkey_patch()  # 필요 시 제거하고 WSGI 서버를 고려
app = create_app()
shutdown_event = threading.Event()  # 종료 이벤트 관리

def handle_shutdown_signal(signum, frame):
    """서버 종료 과정 핸들링."""
    print("서버 종료 신호(Signal: {})를 받았습니다. 봇을 종료하는 중...".format(signum))
    shutdown_event.set()  # 종료하기 위해 이벤트 설정
    try:
        stop_all_bots()  # 모든 봇 종료 (비동기 처리 고려)
    except Exception as e:
        print(f"봇 종료 중 오류 발생: {str(e)}")
    finally:
        print("서버를 종료합니다.")
        sys.exit(0)

# 종료 신호 핸들러 등록
signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
signal.signal(signal.SIGTERM, handle_shutdown_signal)  # 일반 종료 신호

if __name__ == "__main__":
    try:
        # 개발 서버 실행 (운영에서는 gunicorn을 사용 권장)
        print("서버를 시작합니다...")
        socketio.run(app, debug=True, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        handle_shutdown_signal(signal.SIGINT, None)
    except Exception as e:
        print(f"서버 실행 중 오류 발생: {str(e)}")