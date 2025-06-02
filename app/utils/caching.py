import time
import functools
from threading import RLock

# 글로벌 캐시 저장소
_CACHE = {}
_CACHE_LOCK = RLock()


def cache_with_timeout(seconds=30, max_size=100, enable_stats=False):
    """
    함수 결과를 캐싱하는 데코레이터 (개선된 버전)

    Args:
        seconds (int): 캐시 만료 시간 (초)
        max_size (int): 캐시 최대 크기
        enable_stats (bool): 캐시 통계 수집 활성화 여부
    """

    def decorator(func):
        cache_key = f"cache_{func.__name__}"
        stats = {"hits": 0, "misses": 0}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 캐시 키 생성
            key = str(args) + str(sorted(kwargs.items()))

            with _CACHE_LOCK:
                # 캐시 초기화
                if cache_key not in _CACHE:
                    _CACHE[cache_key] = {}

                cache = _CACHE[cache_key]
                now = time.time()

                # 캐시 크기 제한 관리
                if len(cache) >= max_size:
                    # 가장 오래된 항목 제거
                    oldest_key = min(cache.items(), key=lambda x: x[1][1])[0]
                    del cache[oldest_key]

                # 캐시에서 가져오기
                if key in cache:
                    result, timestamp = cache[key]
                    if now - timestamp < seconds:
                        if enable_stats:
                            stats["hits"] += 1
                        return result

                if enable_stats:
                    stats["misses"] += 1

                # 함수 실행 및 결과 캐싱
                result = func(*args, **kwargs)
                cache[key] = (result, now)

                return result

        # 통계 정보 접근을 위한 메서드 추가
        if enable_stats:
            wrapper.get_stats = lambda: {
                "hits": stats["hits"],
                "misses": stats["misses"],
                "hit_ratio": stats["hits"] / (stats["hits"] + stats["misses"]) if (stats["hits"] + stats["misses"]) > 0 else 0
            }

        return wrapper

    return decorator


# 주기적으로 만료된 항목 정리
def cleanup_expired_cache_entries(expiry_seconds=30):
    """
    만료된 캐시 항목을 정리합니다.

    Args:
        expiry_seconds (int): 만료 시간 (초)
    """
    # 문자열로 전달된 경우 정수로 변환
    if isinstance(expiry_seconds, str):
        expiry_seconds = int(expiry_seconds)

    with _CACHE_LOCK:
        now = time.time()
        for cache_key, cache in _CACHE.items():
            expired_keys = [k for k, (_, timestamp) in cache.items()
                            if now - timestamp >= seconds]
            for k in expired_keys:
                del cache[k]


def invalidate_cache():
    """캐시 무효화"""
    with _CACHE_LOCK:
        _CACHE.clear()