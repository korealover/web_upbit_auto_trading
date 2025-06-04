# 업비트 자동 거래 웹 서비스

## 프로젝트 개요

이 프로젝트는 업비트 API를 활용하여 암호화폐 자동 거래를 수행하는 웹 기반 서비스입니다. 볼린저 밴드와 변동성 돌파 전략을 기반으로 매수/매도 신호를 생성하고 자동으로 거래를 수행합니다.

## 주요 기능

- **사용자 계정 관리**: 회원가입, 로그인, 프로필 관리 기능
- **API 키 관리**: 사용자별 업비트 API 키 설정 및 검증
- **자동 거래 봇**: 코인별 자동 거래 봇 설정 및 실행
- **거래 전략 설정**: 볼린저 밴드, 변동성 돌파 전략 설정 가능
- **거래 기록 관리**: 모든 거래 내역을 데이터베이스에 기록하고 대시보드에서 확인 가능
- **텔레그램 알림**: 매수/매도 시 텔레그램으로 알림 전송

## 기술 스택

- **백엔드**: Python 3.13, Flask, SQLAlchemy
- **데이터베이스**: SQLite
- **프론트엔드**: HTML, CSS, JavaScript, Bootstrap
- **패키지 관리**: UV (Python 패키지 매니저)
- **외부 API**: 업비트 API, 텔레그램 API
- **기타 라이브러리**: pyupbit, pandas, numpy

## 시작하기

### 요구 사항

- Python 3.13 이상
- UV 패키지 관리자
- 업비트 API 키 (ACCESS KEY, SECRET KEY)
- (선택) 텔레그램 봇 토큰 및 채팅 ID

### 설치 및 설정

1. 저장소 클론
```shell script
git clone <repository-url>
   cd web_upbit_auto_trading
```


2. 가상 환경 설정
```shell script
python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
```


3. 패키지 설치
```shell script
uv sync
```


4. 환경 변수 설정
   `.env` 파일을 생성하고 다음과 같이 설정:
```
# 업비트 키 및 코드
   UPBIT_ACCESS_KEY=<your-access-key>
   UPBIT_SECRET_KEY=<your-secret-key>
   UPBIT_SERVER_URL=https://api.upbit.com

   # 텔레그램 토큰 및 chat id (선택)
   TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
   TELEGRAM_CHAT_ID=<your-telegram-chat-id>
   TELEGRAM_NOTIFICATIONS_ENABLED=True

   # 캐싱 설정
   CACHE_DURATION_PRICE=1
   CACHE_DURATION_BALANCE=5
   CACHE_DURATION_OHLCV=60
   CACHE_DURATION_PRICE_AVG=10
```


5. 데이터베이스 초기화
```shell script
flask db upgrade
```


6. 관리자 계정 생성 (선택)
```shell script
python create_admin.py
```


7. 서버 실행
```shell script
python run.py
```


## 프로젝트 구조

```
web_upbit_auto_trading/
├── app/                    # 메인 애플리케이션 코드
│   ├── api/                # API 관련 모듈
│   │   └── upbit_api.py    # 업비트 API 래퍼
│   ├── bot/                # 거래 봇 관련 모듈
│   │   └── trading_bot.py  # 자동 거래 봇 클래스
│   ├── strategy/           # 거래 전략 관련 모듈
│   │   └── bollinger.py    # 볼린저 밴드 전략
│   ├── templates/          # HTML 템플릿
│   ├── utils/              # 유틸리티 함수
│   ├── __init__.py         # 앱 초기화
│   ├── forms.py            # 폼 정의
│   ├── models.py           # 데이터베이스 모델
│   └── routes.py           # 라우트 핸들러
├── logs/                   # 로그 파일 디렉토리
├── migrations/             # 데이터베이스 마이그레이션 파일
├── .env                    # 환경 변수 파일
├── app.db                  # SQLite 데이터베이스
├── config.py               # 설정 파일
├── create_admin.py         # 관리자 계정 생성 스크립트
├── pyproject.toml          # 프로젝트 메타데이터
├── requirements.txt        # 패키지 요구사항
└── run.py                  # 실행 스크립트
```


## 거래 전략

### 볼린저 밴드 전략
- 가격이 하단 밴드 아래로 내려가면 매수 신호
- 가격이 상단 밴드 위로 올라가면 매도 신호
- 밴드 내부에 있으면 포지션 유지

### 변동성 돌파 전략
- 전일 변동성의 일정 비율(K값)을 기준으로 매수/매도 신호 생성
- 목표 가격 도달 시 매도, 손실 제한선 도달 시 손절

## 봇 설정 옵션

- **티커**: 거래할 코인 티커 (예: KRW-BTC)
- **차트 간격**: 1분, 3분, 5분, 10분, 30분, 60분, 4시간, 일봉
- **거래 전략**: 볼린저 밴드 또는 변동성 돌파
- **이동평균 기간**: 이동평균 계산에 사용할 기간
- **볼린저 밴드 승수**: 밴드 폭 계산에 사용되는 표준편차 승수
- **매수 금액**: 한 번에 매수할 금액
- **최소 보유 현금량**: 잔고가 이 금액 이하로 떨어지면 매수하지 않음
- **거래 간격**: 거래 신호 확인 간격 (초)
- **K값**: 변동성 돌파 전략의 K값
- **목표 수익률**: 목표 수익률 도달 시 매도
- **손절 손실률**: 손실률이 이 값 이하로 떨어지면 손절
- **매도 비율**: 매도 시 보유량 대비 매도할 비율

## 주의 사항

- 가상 화폐 거래는 높은 위험을 수반합니다.
- 이 프로그램은 투자 조언이 아니며, 모든 거래는 사용자 책임 하에 이루어집니다.
- 실제 자금을 투입하기 전에 충분히 테스트하세요.
- API 키는 안전하게 관리하고, 필요한 권한만 부여하세요.

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

## 기여 방법

1. 이슈 제출 또는 풀 리퀘스트를 통해 기여해주세요.
2. 모든 코드는 PEP 8 스타일 가이드를 따라야 합니다.
3. 새로운 기능을 추가할 때는 적절한 테스트를 작성해주세요.