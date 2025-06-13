from app import create_app, db
from app.models import User
import os
from config import Config
import sys


def create_admin_user(password=None):
    """관리자 계정을 생성하거나 업데이트하는 함수"""
    try:
        # Flask 애플리케이션 인스턴스 생성
        app = create_app()

        with app.app_context():
            admin = User.query.filter_by(username='admin').first()

            if admin is None:
                if password is None:
                    print('오류: 새 관리자 계정 생성을 위해 비밀번호가 필요합니다.')
                    sys.exit(1)

                # 관리자 계정 생성
                admin = User(
                    username='admin',
                    email='admin@example.com',  # 실제 관리자 이메일로 변경 필요
                    upbit_access_key=Config.UPBIT_ACCESS_KEY,
                    upbit_secret_key=Config.UPBIT_SECRET_KEY,
                    is_approved=True,
                    is_admin=True
                )
                admin.set_password(password)
                db.session.add(admin)
                db.session.commit()
                print('관리자 계정이 성공적으로 생성되었습니다.')

            else:
                # 기존 계정 업데이트
                updates = []

                if not admin.is_admin:
                    admin.is_admin = True
                    updates.append('관리자 권한')

                if not admin.is_approved:
                    admin.is_approved = True
                    updates.append('승인 상태')

                # API 키 업데이트 (키가 설정되어 있는 경우에만)
                if Config.UPBIT_ACCESS_KEY and not admin.upbit_access_key:
                    admin.upbit_access_key = Config.UPBIT_ACCESS_KEY
                    updates.append('Upbit Access Key')

                if Config.UPBIT_SECRET_KEY and not admin.upbit_secret_key:
                    admin.upbit_secret_key = Config.UPBIT_SECRET_KEY
                    updates.append('Upbit Secret Key')

                if updates:
                    db.session.commit()
                    print(f'관리자 계정이 업데이트되었습니다. 변경사항: {", ".join(updates)}')
                else:
                    print('관리자 계정이 이미 존재하며 모든 설정이 완료되어 있습니다.')

    except Exception as e:
        print(f'오류 발생: {str(e)}')
        sys.exit(1)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='관리자 계정 생성/업데이트 스크립트')
    parser.add_argument('--password', help='새 관리자 계정을 위한 비밀번호')
    args = parser.parse_args()

    create_admin_user(args.password)