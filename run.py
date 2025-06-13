from app import create_app, socketio
import eventlet

eventlet.monkey_patch()
app = create_app()

if __name__ == '__main__':
    # WebSocket 서버 설정
    socketio.run(app,
                debug=True,
                host='0.0.0.0',
                port=5000,
                allow_unsafe_werkzeug=True,
                ping_timeout=60,
                ping_interval=25,
                cors_allowed_origins="*")