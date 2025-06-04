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

    # 애플리케이션 컨텍스트 내에서 작업 수행
    with app.app_context():
        # 데이터베이스 테이블 생성
        db.create_all()

        # 관리자 계정이 있는지 확인
        admin = User.query.filter_by(username='admin').first()
        if admin is None:
            # 관리자 계정 생성 (기본 API 키 사용)
            admin = User(
                username='admin',
                email='jhsun3692@gmail.com',
                upbit_access_key=Config.UPBIT_ACCESS_KEY,
                upbit_secret_key=Config.UPBIT_SECRET_KEY
            )
            admin.set_password('admin123')  # 실제 사용 시 더 강력한 비밀번호 사용 권장
            db.session.add(admin)
            db.session.commit()
            print('관리자 계정이 생성되었습니다.')
            print(f'기본 업비트 API 키가 설정되었습니다.')
        else:
            print('관리자 계정이 이미 존재합니다.')

            # 기존 관리자 계정에 API 키가 없는 경우 업데이트
            updated = False
            if not admin.upbit_access_key:
                admin.upbit_access_key = Config.UPBIT_ACCESS_KEY
                updated = True
            if not admin.upbit_secret_key:
                admin.upbit_secret_key = Config.UPBIT_SECRET_KEY
                updated = True

            if updated:
                db.session.commit()
                print(f'기존 관리자 계정에 업비트 API 키가 업데이트되었습니다.')


if __name__ == '__main__':
    create_admin_user()