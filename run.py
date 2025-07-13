from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    # 환경변수에서 설정 로드
    app.config.from_object('config.Config')

    # 확장 기능 초기화
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.login_message = '로그인이 필요합니다.'

    # 블루프린트 등록
    from app.routes import bp as main_bp
    app.register_blueprint(main_bp)

    # 로그 설정
    if not app.debug:
        if not os.path.exists('logs'):
            os.mkdir('logs')

        file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
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


app = create_app()
app.run(debug=True, host='0.0.0.0', port=5000)
