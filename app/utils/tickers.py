# app/utils/tickers.py
"""
업비트 코인 티커 목록을 관리하는 모듈
"""

# 주요 코인 티커 목록 (KRW 마켓)
MAJOR_TICKERS = [
    ('KRW-ADA', '에이다(ADA)'),
    ('KRW-ANIME', '애니메코인(ANIME)'),
    ('KRW-BTC', '비트코인(BTC)'),
    ('KRW-DOGE', '도지코인(DOGE)'),
    ('KRW-ETH', '이더리움(ETH)'),
    ('KRW-ICX', '아이콘(ICX)'),
    ('KRW-KAITO', '카이토(KAITO)'),
    ('KRW-SAHARA', '사하라에이아이(SAHARA)'),
    ('KRW-SHIB', '시바이누(SHIB)'),
    ('KRW-TRUMP', '오피셜트럼프(TRUMP)'),
    ('KRW-USDT', '테더(USDT)'),
    ('KRW-XLM', '스텔라루멘(XLM)'),
    ('KRW-XRP', '리플(XRP)'),
]


def get_ticker_choices():
    """
    폼에서 사용할 수 있는 티커 선택 옵션 목록을 반환합니다.

    Returns:
        list: (티커, 표시명) 튜플의 리스트
    """
    return MAJOR_TICKERS


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
        # 알파벳(사전)순으로 정렬
        sorted_tickers = sorted(all_tickers)
        # print(sorted_tickers)

        # 티커 정보 가공 (티커와 이름 표시)
        updated_tickers = []
        for ticker in sorted_tickers:
            # 심볼만 추출 (KRW- 제거)
            symbol = ticker.replace("KRW-", "")
            updated_tickers.append((ticker, f'{symbol}({symbol})'))

        # 글로벌 변수 업데이트
        global MAJOR_TICKERS
        # 기존 주요 티커는 상위에 유지하고 나머지 추가
        major_symbols = [t[0] for t in MAJOR_TICKERS]
        for ticker in updated_tickers:
            if ticker[0] not in major_symbols:
                MAJOR_TICKERS.append(ticker)

        return True
    except Exception as e:
        print(f"티커 업데이트 중 오류 발생: {str(e)}")
        return False