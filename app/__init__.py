# app/__init__.py
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
import logging
from datetime import datetime

# 글로벌 객체들
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
socketio = SocketIO()


def create_app():
    """Flask 앱 팩토리"""
    app = Flask(__name__)

    # 설정 로드
    app.config.from_object('config.Config')

    # 확장 초기화
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet')

    # 로그인 설정
    login_manager.login_view = 'main.login'
    login_manager.login_message = '로그인이 필요합니다.'

    # 블루프린트 등록
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)

    # 로깅 설정
    if not app.debug:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        today = datetime.now().strftime('%Y%m%d')
        file_handler = logging.FileHandler(f'logs/{today}_app.log')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Application startup')

    # 스케줄러 초기화 (애플리케이션 컨텍스트에서 실행)
    with app.app_context():
        initialize_scheduler(app)

    return app

def initialize_scheduler(app):
    """스케줄러 초기화"""
    try:
        from app.utils.scheduler_manager import scheduler_manager
        if not scheduler_manager.is_started():
            scheduler_manager.start()
            app.logger.info("트레이딩 스케줄러가 시작되었습니다.")
    except Exception as e:
        app.logger.error(f"스케줄러 초기화 실패: {e}")


# Gunicorn에서 직접 임포트할 수 있도록 앱 인스턴스 생성
app = create_app()