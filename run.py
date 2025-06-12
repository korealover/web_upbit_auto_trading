
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    # WebSocket을 지원하는 서버 실행
    socketio.run(app,
                debug=True,
                host='0.0.0.0',
                port=5000,
                allow_unsafe_werkzeug=True)