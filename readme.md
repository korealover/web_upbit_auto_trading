# 업비트 자동 거래 웹 서비스

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-latest-green.svg)](https://flask.palletsprojects.com/)
[![UV Package Manager](https://img.shields.io/badge/uv-latest-purple.svg)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

암호화폐 자동 거래를 위한 웹 기반 플랫폼입니다. 볼린저 밴드와 변동성 돌파 전략을 기반으로 한 자동 거래 시스템을 제공합니다.

## 🚀 주요 기능

### 👤 사용자 관리
- 회원가입 및 로그인 시스템
- 관리자 승인 기반 사용자 관리
- 프로필 설정 및 API 키 관리
- 다단계 보안 인증

### 🤖 자동 거래
- 실시간 시장 모니터링
- 다중 코인 동시 거래 지원
- 사용자별 독립적인 거래 봇 운영
- 실시간 거래 상태 모니터링

### 📊 거래 전략
- 볼린저 밴드 전략
- 변동성 돌파 전략
- 사용자 정의 매매 조건 설정
- 실시간 전략 성과 분석

### 📱 알림 시스템
- 텔레그램 실시간 알림
- 거래 실행 알림
- 시스템 상태 알림
- 에러 및 경고 알림

## 🛠 기술 스택

### 백엔드
- Python 3.13
- Flask Framework
- SQLAlchemy ORM
- Flask-SocketIO
- Flask-Login
- Flask-Migrate

### 프론트엔드
- Bootstrap 5
- Chart.js
- Socket.IO-client
- jQuery

### 데이터베이스 & 캐싱
- SQLite
- Redis (캐싱)

### 인프라
- UV 패키지 관리자
- Docker 지원
- GitHub Actions CI/CD

## ⚙️ 설치 가이드

### 사전 요구사항
- Python 3.13+
- UV 패키지 관리자
- Git
- 업비트 API 키셋
- (선택) 텔레그램 봇 토큰

### 기본 설치

1. **저장소 클론**
```bash 
git clone (https://github.com/yourusername/web_upbit_auto_trading.git) cd web_upbit_auto_trading
``` 

2. **가상환경 설정**
```bash 
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/MacOS
source .venv/bin/activate
``` 

3. **의존성 설치**
```bash 
uv sync
``` 

### 환경 설정

1. **환경 변수 설정**
`.env.example`을 `.env`로 복사하고 필요한 값을 설정:
```bash 
cp .env.example .env
``` 

필수 환경 변수:
```bash
# 서버 설정
FLASK_APP=run.py FLASK_ENV=development SECRET_KEY=your-secret-key

# 업비트 API
UPBIT_ACCESS_KEY=your-access-key 
UPBIT_SECRET_KEY=your-secret-key 
UPBIT_SERVER_URL=https://api.upbit.com

# 텔레그램 설정 (선택)
TELEGRAM_BOT_TOKEN=your-bot-token 
TELEGRAM_CHAT_ID=your-chat-id 
TELEGRAM_NOTIFICATIONS_ENABLED=True

# 캐싱 설정
CACHE_DURATION_PRICE=1
CACHE_DURATION_BALANCE=5
CACHE_DURATION_OHLCV=60
CACHE_DURATION_PRICE_AVG=10
``` 

2. **데이터베이스 초기화**
```bash 
flask db upgrade
``` 

3. **관리자 계정 생성**
```bash 
python create_admin.py --password "your-secure-password"
``` 

## 🚦 실행 방법

### 개발 환경
```bash 
python run.py
``` 

### 프로덕션 환경
```bash 
gunicorn -w 4 -k gevent 'run:create_app()'
``` 

## 📊 거래 전략 상세

### 볼린저 밴드 전략
- **매수 조건**: 가격이 하단 밴드 하향 돌파
- **매도 조건**: 가격이 상단 밴드 상향 돌파
- **설정 가능 파라미터**:
  - 이동평균 기간 (기본값: 20)
  - 표준편차 승수 (기본값: 2.0)
  - 거래량 필터링

### 변동성 돌파 전략
- **매수 조건**: (전일 고가 - 전일 저가) × K 값
- **매도 조건**: 목표가 도달 또는 손절가 도달
- **설정 가능 파라미터**:
  - K값 (기본값: 0.5)
  - 손절률
  - 익절률

## 🔧 문제 해결

### 일반적인 문제
- **API 연결 오류**: API 키 재확인 및 네트워크 상태 점검
- **거래 실행 실패**: 잔고 및 최소 주문 금액 확인
- **봇 작동 중단**: 로그 확인 및 서버 상태 점검

### 로그 확인
- 로그 파일 위치: `logs/`
- 에러 로그: `logs/error.log`
- 거래 로그: `logs/trading.log`

## 📝 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## ⚠️ 면책 조항

이 소프트웨어는 "있는 그대로" 제공되며, 어떠한 형태의 보증도 제공되지 않습니다. 
가상화폐 거래에는 상당한 위험이 따르며, 이 소프트웨어를 사용하여 발생하는 
모든 금전적 손실에 대해 개발자는 책임을 지지 않습니다.
```
