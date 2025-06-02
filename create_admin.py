from app import app, db
from app.models import User
import os


def create_admin_user():
    # 데이터베이스 설정
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, "app.db")

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
            # 관리자 계정 생성
            admin = User(username='admin', email='jhsun3692@gmail.com')
            admin.set_password('admin123')  # 실제 사용 시 더 강력한 비밀번호 사용 권장
            db.session.add(admin)
            db.session.commit()
            print('관리자 계정이 생성되었습니다.')
        else:
            print('관리자 계정이 이미 존재합니다.')


if __name__ == '__main__':
    create_admin_user()