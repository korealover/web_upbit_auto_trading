"""
텔레그램 유틸리티 테스트 스크립트
"""
import os
import sys
import logging
from datetime import datetime
import time

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 환경 변수 로드를 위한 임시 설정
os.environ['FLASK_ENV'] = 'testing'

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_telegram_notifier():
    """텔레그램 알림 기능 테스트"""
    try:
        # 환경 변수에서 텔레그램 토큰과 채팅 ID 가져오기
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not telegram_token or not telegram_chat_id:
            logger.error("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경 변수가 설정되지 않았습니다.")
            logger.info("환경 변수를 설정하거나 .env 파일에 다음 값들을 추가하세요:")
            logger.info("TELEGRAM_BOT_TOKEN=your_bot_token")
            logger.info("TELEGRAM_CHAT_ID=your_chat_id")
            return False

        # 텔레그램 알림 클래스 임포트
        from app.utils.telegram_utils import TelegramNotifier

        # 테스트 사용자명
        test_username = "테스트봇"

        # TelegramNotifier 인스턴스 생성
        logger.info("텔레그램 알림 인스턴스 생성 중...")
        notifier = TelegramNotifier(
            token=telegram_token,
            chat_id=telegram_chat_id,
            logger=logger,
            usename=test_username
        )

        # 잠시 대기 (비동기 컴포넌트 초기화)
        time.sleep(1)

        # 1. 기본 메시지 전송 테스트
        logger.info("기본 메시지 전송 테스트...")
        test_message = f"📢 텔레그램 알림 테스트\n시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        result1 = notifier.send_message(test_message)
        logger.info(f"기본 메시지 전송 결과: {'성공' if result1 else '실패'}")

        # 2. 매수 알림 테스트
        logger.info("매수 알림 테스트...")
        result2 = notifier.send_trade_message(
            trade_type="매수",
            ticker="KRW-BTC",
            amount=50000,
            price=160000000,
            volume=0.0003125
        )
        logger.info(f"매수 알림 전송 결과: {'성공' if result2 else '실패'}")

        # 3. 매도 알림 테스트
        logger.info("매도 알림 테스트...")
        result3 = notifier.send_trade_message(
            trade_type="매도",
            ticker="KRW-ETH",
            amount=0.025,
            price=4000000,
            volume=100000
        )
        logger.info(f"매도 알림 전송 결과: {'성공' if result3 else '실패'}")

        # 4. 마크다운 형식 메시지 테스트
        logger.info("마크다운 형식 메시지 테스트...")
        markdown_message = """
*텔레그램 알림 테스트 완료*
───────────────────
• 기본 메시지: `✅ 성공`
• 매수 알림: `✅ 성공`
• 매도 알림: `✅ 성공`
• 마크다운: `✅ 성공`

테스트 완료 시간: `{}`
        """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        result4 = notifier.send_message(markdown_message)
        logger.info(f"마크다운 메시지 전송 결과: {'성공' if result4 else '실패'}")

        # 전체 테스트 결과
        all_success = all([result1, result2, result3, result4])
        logger.info(f"전체 테스트 결과: {'모두 성공' if all_success else '일부 실패'}")

        return all_success

    except ImportError as e:
        logger.error(f"모듈 임포트 실패: {e}")
        return False
    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {e}")
        return False


def test_telegram_bot_connection():
    """텔레그램 봇 연결 테스트"""
    try:
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not telegram_token or not telegram_chat_id:
            logger.error("환경 변수가 설정되지 않았습니다.")
            return False

        # 직접 HTTP 요청으로 봇 연결 테스트
        import requests

        # 봇 정보 가져오기
        logger.info("텔레그램 봇 정보 확인 중...")
        bot_info_url = f"https://api.telegram.org/bot{telegram_token}/getMe"
        response = requests.get(bot_info_url, timeout=10)

        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                logger.info(f"봇 정보: {bot_info['result']['username']}")
                logger.info("텔레그램 봇 연결 성공")
                return True
            else:
                logger.error(f"봇 정보 조회 실패: {bot_info}")
                return False
        else:
            logger.error(f"HTTP 요청 실패: {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"봇 연결 테스트 중 오류: {e}")
        return False


def main():
    """메인 테스트 함수"""
    logger.info("=== 텔레그램 유틸리티 테스트 시작 ===")

    # 환경 변수 로드 (.env 파일이 있는 경우)
    try:
        from dotenv import load_dotenv
        load_dotenv()
        logger.info(".env 파일에서 환경 변수 로드 완료")
    except ImportError:
        logger.warning("python-dotenv가 설치되지 않았습니다. 환경 변수를 직접 설정하세요.")
    except Exception as e:
        logger.warning(f".env 파일 로드 중 오류: {e}")

    # 1. 봇 연결 테스트
    logger.info("1. 텔레그램 봇 연결 테스트")
    connection_ok = test_telegram_bot_connection()

    if not connection_ok:
        logger.error("텔레그램 봇 연결 실패. 환경 변수를 확인하세요.")
        return

    # 2. 알림 기능 테스트
    logger.info("2. 텔레그램 알림 기능 테스트")
    notification_ok = test_telegram_notifier()

    if notification_ok:
        logger.info("=== 모든 테스트 완료: 성공 ===")
    else:
        logger.error("=== 일부 테스트 실패 ===")


if __name__ == "__main__":
    main()