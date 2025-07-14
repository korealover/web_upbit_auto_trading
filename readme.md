# 업비트 자동 거래 웹 서비스

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-latest-green.svg)](https://flask.palletsprojects.com/)
[![UV Package Manager](https://img.shields.io/badge/uv-latest-purple.svg)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 📖 개요

**업비트 자동 거래 웹 서비스**는 변동성 돌파 및 볼린저 밴드와 같은 정교한 거래 전략을 사용하여 암호화폐 시장에서 자동 거래를 수행하는 웹 기반 플랫폼입니다. 실시간 데이터 처리, 다중 코인 거래, 사용자별 독립 봇 운영 등 강력한 기능을 제공하여 사용자가 전략을 효과적으로 관리하고 모니터링할 수 있도록 지원합니다.

---

## 🚀 주요 기능

### 👤 사용자 관리
- **보안 인증**: 안전한 회원가입 및 로그인 시스템을 제공합니다.
- **관리자 대시보드**: 관리자 승인을 통해 사용자를 효율적으로 관리합니다.
- **API 키 관리**: 사용자가 자신의 업비트 API 키를 안전하게 저장하고 관리할 수 있습니다.

### 🤖 자동 거래
- **실시간 모니터링**: 웹소켓을 통해 시장 상황을 실시간으로 모니터링합니다.
- **다중 코인 거래**: 여러 암호화폐를 동시에 자동 거래할 수 있습니다.
- **독립적인 거래 봇**: 각 사용자별로 독립적인 거래 봇이 할당되어 안정적인 운영을 보장합니다.
- **거래 현황**: 대시보드에서 실시간 거래 상태와 내역을 확인할 수 있습니다.

### 📊 거래 전략 및 분석
- **다양한 전략**: 볼린저 밴드, 변동성 돌파 등 입증된 거래 전략을 제공합니다.
- **사용자 정의 설정**: 이동평균 기간, K값 등 전략별 파라미터를 사용자가 직접 설정할 수 있습니다.
- **성과 분석**: `pandas`와 `matplotlib`을 활용하여 거래 데이터를 분석하고 시각화합니다. (기능 추가 예정)

### 📱 알림 시스템
- **텔레그램 연동**: 거래 체결, 시스템 상태, 오류 발생 시 텔레그램으로 실시간 알림을 보냅니다.

---

## 🛠 기술 스택

| 구분 | 기술 | 설명 |
|---|---|---|
| **Backend** | Python 3.13, Flask, Flask-SocketIO | 안정적인 백엔드 서버 및 실시간 통신 |
| **Database** | SQLAlchemy, Flask-Migrate, SQLite, MySQL | 유연한 데이터베이스 관리 (개발: SQLite, 프로덕션: MySQL 권장) |
| **Frontend** | Bootstrap 5, Socket.IO-client, jQuery | 반응형 웹 디자인 및 동적 UI/UX |
| **Data Analysis** | pandas, matplotlib | 거래 데이터 분석 및 시각화 |
| **API** | Upbit API, Telegram Bot API | 외부 서비스 연동 |
| **Deployment** | Gunicorn, Eventlet | 프로덕션 환경을 위한 고성능 서버 |
| **Package Manager** | UV | 빠르고 효율적인 의존성 관리 |

---

## 📂 프로젝트 구조
``` 
web_upbit_auto_trading/ 
├── app/ # 핵심 애플리케이션 모듈 
│ ├── api/ # 외부 API (Upbit) 핸들러 
│ ├── bot/ # 거래 봇 로직 
│ ├── static/ # 정적 파일 (CSS, JS, Images) 
│ ├── strategy/ # 거래 전략 알고리즘 
│ ├── templates/ # HTML 템플릿 
│ ├── utils/ # 유틸리티 함수 
│ ├── __init__.py # 애플리케이션 팩토리 
│ ├── forms.py # WTForms 양식 정의 
│ ├── models.py # SQLAlchemy 모델 정의 
│ ├── routes.py # 라우팅 및 뷰 함수 
│ └── websocket_handlers.py # 웹소켓 이벤트 핸들러 
├── db/ # 데이터베이스 파일 
├── logs/ # 로그 파일 
├── migrations/ # 데이터베이스 마이그레이션 스크립트 
├── .env # 환경 변수 파일 
├── config.py # 설정 파일 
├── pyproject.toml # 프로젝트 의존성 및 메타데이터 
├── run.py # 애플리케이션 실행 스크립트 
└── readme.md # 프로젝트 설명서
```

---

## ⚙️ 설치 및 실행

### 사전 요구사항
- Python 3.13+
- UV 패키지 관리자
- Git
- 업비트 API 키
- (선택) 텔레그램 봇 토큰 및 채팅 ID

### 설치 과정

1.  **저장소 복제**
    ```bash
    git clone https://github.com/korealover/web_upbit_auto_trading.git
    cd web_upbit_auto_trading
    ```

2.  **가상 환경 생성 및 활성화**
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **의존성 설치**
    ```bash
    uv sync
    ```

### 환경 설정

1.  **.env 파일 설정**
    `.env.example` 파일을 `.env`로 복사하고, 아래 내용을 자신의 환경에 맞게 수정하세요.
    ```bash
    cp .env.example .env
    ```

    **필수 환경 변수:**
    ```ini
    # 업비트 키 및 코드
    UPBIT_ACCESS_KEY=upbit_access_key
    UPBIT_SECRET_KEY=upbit_secret_key
    UPBIT_SERVER_URL=https://api.upbit.com
    
    # 텔리그램 토큰 및 chat id
    TELEGRAM_BOT_TOKEN=telegram_bot_token
    TELEGRAM_CHAT_ID=telegram_chat_id_group
    TELEGRAM_CHAT_ID_PERSONAL=telegram_chat_id
    TELEGRAM_NOTIFICATIONS_ENABLED=True
    
    # 캐싱 설정
    CACHE_DURATION_PRICE=1
    CACHE_DURATION_BALANCE=5
    CACHE_DURATION_OHLCV=60
    CACHE_DURATION_PRICE_AVG=10
    ```

2.  **데이터베이스 초기화**
    ```bash
    flask db init
    flask db upgrade
    ```

3.  **관리자 계정 생성**
    ```bash
    python create_admin.py --password "your-secure-password"
    ```

### 실행 방법

-   **개발 환경**
    ```bash
    flask run
    ```

-   **프로덕션 환경**
    ```bash
    gunicorn -w 4 -k gevent 'run:create_app()'
    ```

---

## 📝 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

---

## ⚠️ 면책 조항

본 소프트웨어는 "있는 그대로" 제공되며, 명시적이든 묵시적이든 어떠한 종류의 보증도 하지 않습니다. 암호화폐 거래는 상당한 위험을 수반하며, 본 소프트웨어 사용으로 인해 발생하는 어떠한 금전적 손실에 대해서도 개발자는 책임을 지지 않습니다. 투자 결정은 전적으로 사용자의 책임입니다.
