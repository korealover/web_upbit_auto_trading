from app import create_app

# 개발 환경에서만 사용하는 간단한 실행 파일
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
