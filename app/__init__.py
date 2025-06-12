from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
import os
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
socketio = SocketIO()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 확장 프로그램 초기화
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # SocketIO 초기화 (CORS 설정 포함)
    socketio.init_app(app,
                      cors_allowed_origins="*",
                      logger=True,
                      engineio_logger=True,
                      async_mode='threading')

    # 로그인 매니저 설정 - Blueprint 사용으로 인한 endpoint 변경
    login_manager.login_view = 'main.login'
    login_manager.login_message = '이 페이지에 접근하려면 로그인이 필요합니다.'
    login_manager.login_message_category = 'info'

    # 블루프린트 등록
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)

    # SocketIO 이벤트 핸들러 등록
    from app.websocket_handlers import register_socketio_handlers
    register_socketio_handlers(socketio)

    return app


from app import models