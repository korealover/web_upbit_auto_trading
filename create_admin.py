from app import app, db
from app.models import User
import os
from config import Config


def create_admin_user():
    # 데이터베이스 설정
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, "db", "app.db")

    # 데이터베이스 URI 설정 (이미 설정되어 있지 않은 경우)
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 관리자 계정이 있는지 확인
    with app.app_context():  # 애플리케이션 컨텍스트 추가
        admin = User.query.filter_by(username='admin').first()
        if admin is None:
            # 관리자 계정 생성
            admin = User(
                username='admin',
                email='admin@admin.ai',
                upbit_access_key=Config.UPBIT_ACCESS_KEY,
                upbit_secret_key=Config.UPBIT_SECRET_KEY,
                is_approved=True,  # 승인 상태
                is_admin=True  # 관리자 권한
            )
            admin.set_password('!admin123')
            db.session.add(admin)
            db.session.commit()
            print('관리자 계정이 생성되었습니다.')
        else:
            # 기존 계정에 관리자 권한 추가
            if not admin.is_admin:
                admin.is_admin = True
            if not admin.is_approved:
                admin.is_approved = True

            # API 키 업데이트
            updated = False
            if not admin.upbit_access_key:
                admin.upbit_access_key = Config.UPBIT_ACCESS_KEY
                updated = True
            if not admin.upbit_secret_key:
                admin.upbit_secret_key = Config.UPBIT_SECRET_KEY
                updated = True

            if updated or admin.is_admin or admin.is_approved:
                db.session.commit()
                print('관리자 권한이 업데이트되었습니다.')
            else:
                print('관리자 계정이 이미 존재합니다.')


if __name__ == '__main__':
    create_admin_user()