# app/__init__.py
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
import logging
from datetime import datetime
import uuid
import time
from app.utils.shared import scheduled_bots

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
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Application startup')

    # 스케줄러 초기화 (애플리케이션 컨텍스트에서 실행)
    with app.app_context():
        initialize_scheduler(app)

    return app


def get_interval_label(interval_value):
    """간격 값을 한글 라벨로 변환"""
    interval_mapping = {
        'day': '일봉',
        'minute1': '1분',
        'minute3': '3분',
        'minute5': '5분',
        'minute10': '10분',
        'minute15': '15분',
        'minute30': '30분',
        'minute60': '60분',
        'minute240': '240분'
    }
    return interval_mapping.get(interval_value, str(interval_value))

# 초기화
def initialize_scheduler(app):
    """스케줄러 초기화 및 DB의 trading_favorite 데이터로 작업 복원"""
    try:
        from app.utils.scheduler_manager import scheduler_manager
        from app.models import TradingFavorite
        from app.routes import scheduled_trading_cycle, create_trading_bot_from_favorite

        if not scheduler_manager.is_started():
            scheduler_manager.start()
            app.logger.info("트레이딩 스케줄러가 시작되었습니다.")

        # DB에서 trading_favorite 데이터 가져오기 (user_id, ticker 조합별로 최신 것만)
        favorites = TradingFavorite.query.filter_by(start_yn='Y').order_by(TradingFavorite.id.asc()).all()
        if favorites:
            # user_id와 ticker 조합별로 중복 제거 (최신 것만 유지)
            unique_favorites = {}
            for favorite in favorites:
                key = (favorite.user_id, favorite.ticker)
                if key not in unique_favorites:
                    unique_favorites[key] = favorite

            favorites = list(unique_favorites.values())
            restored_count = 0

            for favorite in favorites:
                try:
                    # 봇 생성
                    bot, settings = create_trading_bot_from_favorite(favorite)
                    if bot is None:
                        app.logger.error(f"봇 생성 실패: {favorite.name} ({favorite.ticker})")
                        continue

                    # 작업 ID 생성
                    job_id = f"Trading_bot_{favorite.user_id}_{favorite.ticker}_{favorite.strategy}_{uuid.uuid4().hex[:8]}"

                    # 스케줄러용 래퍼 함수 생성
                    def create_scheduled_wrapper(user_id, ticker, bot_instance):
                        def wrapper():
                            scheduled_trading_cycle(user_id, ticker, bot=bot_instance)

                        return wrapper

                    trading_func = create_scheduled_wrapper(favorite.user_id, favorite.ticker, bot)

                    # 스케줄러에 작업 추가
                    success = scheduler_manager.add_trading_job(
                        job_id=job_id,
                        trading_func=trading_func,
                        interval_seconds=favorite.sleep_time,
                        user_id=favorite.user_id,
                        ticker=favorite.ticker,
                        strategy=favorite.strategy
                    )

                    if success:
                        # scheduled_bots 딕셔너리에 사용자 ID 키가 없으면 생성
                        if favorite.user_id not in scheduled_bots:
                            scheduled_bots[favorite.user_id] = {}
                        else:
                            if favorite.ticker in scheduled_bots[favorite.user_id]:
                                old_job_id = scheduled_bots[favorite.user_id][favorite.ticker]['job_id']
                                scheduler_manager.remove_job(old_job_id)
                                app.logger.info(f"기존 스케줄 작업 중지: {favorite.user_id} / {favorite.ticker} / {old_job_id}")
                                time.sleep(1)

                        with scheduler_manager.lock:
                            scheduled_bots[favorite.user_id][favorite.ticker] = {
                                'job_id': job_id,
                                'bot': bot,
                                'strategy': favorite.strategy,
                                'settings': settings,
                                'interval': favorite.sleep_time,
                                'start_time': datetime.now(),
                                'username': settings['username'],
                                'cycle_count': 0,
                                'last_run': None,
                                'running': True,  # 실행 상태 추가
                                'interval_label': get_interval_label(favorite.interval),  # 수정된 부분: sleep_time 직접 전달
                                'long_term_investment': favorite.long_term_investment
                            }
                        restored_count += 1
                        app.logger.info(f"트레이딩 작업 복원: {favorite.name} ({favorite.ticker})")

                    else:
                        app.logger.error(f"트레이딩 작업 복원 실패: {favorite.name} ({favorite.ticker})")

                except Exception as e:
                    app.logger.error(f"즐겨찾기 복원 중 오류 ({favorite.name}): {e}")

                time.sleep(3) # 3초씩 여유를 두고 재실행

            app.logger.info(f"총 {restored_count}개의 트레이딩 작업이 복원되었습니다.")
        else:
            app.logger.info("즐겨찾기 데이터가 없습니다.")
    except Exception as e:
        app.logger.error(f"스케줄러 초기화 실패: {e}")


# Gunicorn에서 직접 임포트할 수 있도록 앱 인스턴스 생성
app = create_app()

