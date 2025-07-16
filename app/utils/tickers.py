# app/utils/tickers.py
"""
업비트 코인 티커 목록을 관리하는 모듈
"""

# 주요 코인 티커 목록 (KRW 마켓) - 기본값 설정
MAJOR_TICKERS = [
    ('KRW-BTC', '비트코인(BTC)'),
    ('KRW-DOGE', '도지코인(DOGE)'),
    ('KRW-ETH', '이더리움(ETH)'),
    ('KRW-SOL', '솔라나(SOL)'),
    ('KRW-USDT', '테더(USDT)'),
    ('KRW-XLM', '스텔라루멘(XLM)'),
    ('KRW-XRP', '리플(XRP)'),
]


def get_ticker_choices():
    """
    폼에서 사용할 수 있는 티커 선택 옵션 목록을 반환합니다.
    만약 MAJOR_TICKERS가 비어있다면 기본 티커를 먼저 업데이트합니다.

    Returns:
        list: (티커, 표시명) 튜플의 리스트
    """
    global MAJOR_TICKERS

    # 티커 목록이 기본값만 있거나 비어있는 경우 업데이트 시도
    if len(MAJOR_TICKERS) <= 10:  # 기본값 10개보다 적거나 같으면
        try:
            update_tickers_from_upbit()
        except Exception as e:
            print(f"티커 업데이트 실패, 기본값 사용: {str(e)}")

    return MAJOR_TICKERS if MAJOR_TICKERS else [('KRW-BTC', 'BTC (비트코인)')]


def get_ticker_by_symbol(symbol):
    """
    심볼로 티커 정보를 조회합니다.

    Args:
        symbol (str): 조회할 코인 심볼 (예: 'KRW-BTC')

    Returns:
        tuple: (티커, 표시명) 튜플, 없으면 None
    """
    for ticker in MAJOR_TICKERS:
        if ticker[0] == symbol:
            return ticker
    return None


def update_tickers_from_upbit():
    """
    업비트 API를 통해 실시간 티커 목록을 업데이트합니다.
    """
    try:
        import pyupbit
        # 원화 마켓의 모든 티커 가져오기
        all_tickers = pyupbit.get_tickers(fiat="KRW")

        if not all_tickers:
            print("업비트에서 티커를 가져올 수 없습니다.")
            return False

        # 알파벳(사전)순으로 정렬
        sorted_tickers = sorted(all_tickers)

        # 티커 정보 가공 (티커와 이름 표시)
        updated_tickers = []
        for ticker in sorted_tickers:
            # 심볼만 추출 (KRW- 제거)
            symbol = ticker.replace("KRW-", "")
            updated_tickers.append((ticker, f'{symbol} ({symbol})'))

        # 글로벌 변수 업데이트
        global MAJOR_TICKERS

        # 기존 주요 티커 심볼 목록
        major_symbols = [t[0] for t in MAJOR_TICKERS]

        # 새로운 티커만 추가
        for ticker in updated_tickers:
            if ticker[0] not in major_symbols:
                MAJOR_TICKERS.append(ticker)

        # print(f"티커 업데이트 완료: {len(MAJOR_TICKERS)}개")
        return True

    except ImportError:
        print("pyupbit 모듈을 찾을 수 없습니다. 기본 티커를 사용합니다.")
        return False
    except Exception as e:
        print(f"티커 업데이트 중 오류 발생: {str(e)}")
        return False


# 모듈 초기화시 한번 티커 업데이트 시도
def initialize_tickers():
    """
    모듈 초기화 시 티커 목록을 업데이트합니다.
    """
    try:
        update_tickers_from_upbit()
    except Exception as e:
        print(f"초기 티커 업데이트 실패: {str(e)}")


# 모듈 로드 시 자동으로 티커 초기화
if __name__ != "__main__":
    initialize_tickers()
    