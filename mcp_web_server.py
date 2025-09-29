# mcp_web_server.py
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 기존 프로젝트 설정 import
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# SocketIO 설정 - Config에서 가져오기
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=Config.SOCKETIO_ASYNC_MODE,
    ping_timeout=Config.SOCKETIO_PING_TIMEOUT,
    ping_interval=Config.SOCKETIO_PING_INTERVAL
)


# 인증 미들웨어 개선
@app.before_request
def verify_auth():
    """API 호출 시 인증 확인"""
    # GET /mcp/tools는 인증 없이 허용
    if request.endpoint == 'get_tools' or request.endpoint is None:
        return

    # POST 요청은 인증 토큰 확인
    if request.method == 'POST' and request.endpoint == 'execute_tool':
        auth_header = request.headers.get('Authorization')
        expected_token = f"Bearer {Config.MCP_AUTH_TOKEN}"

        if not auth_header or auth_header != expected_token:
            return jsonify({"error": "Unauthorized access"}), 401


# 헬스 체크 엔드포인트 추가
@app.route('/health', methods=['GET'])
def health_check():
    """서버 상태 확인"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0.0"
    })


@app.route('/mcp/tools', methods=['GET'])
def get_tools():
    """사용 가능한 도구 목록 반환"""
    tools = [
        {
            "name": "get_coin_price",
            "description": "특정 가상화폐의 현재 가격 정보를 조회합니다.",
            "parameters": {
                "ticker": {
                    "type": "string",
                    "description": "가상화폐 티커 (예: KRW-BTC, KRW-ETH)",
                    "required": True
                }
            }
        },
        {
            "name": "get_portfolio_status",
            "description": "사용자의 현재 포트폴리오 상태를 조회합니다.",
            "parameters": {
                "user_id": {
                    "type": "integer",
                    "description": "사용자 ID",
                    "default": 1
                }
            }
        },
        {
            "name": "analyze_trading_performance",
            "description": "특정 기간 동안의 매매 성과를 분석합니다.",
            "parameters": {
                "user_id": {
                    "type": "integer",
                    "description": "사용자 ID",
                    "default": 1
                },
                "days": {
                    "type": "integer",
                    "description": "분석할 일수 (1-30)",
                    "default": 7
                }
            }
        },
        {
            "name": "check_investment_recommendation",
            "description": "특정 가상화폐의 투자 여부를 분석하여 추천합니다.",
            "parameters": {
                "ticker": {
                    "type": "string",
                    "description": "가상화폐 티커",
                    "required": True
                }
            }
        }
    ]
    return jsonify({
        "tools": tools,
        "server_info": {
            "name": "upbit-trading-analysis",
            "version": "1.0.0",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    })


@app.route('/mcp/execute', methods=['POST'])
def execute_tool():
    """도구 실행"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        tool_name = data.get('tool')
        parameters = data.get('parameters', {})

        if not tool_name:
            return jsonify({"error": "Tool name is required"}), 400

        # 도구별 실행
        if tool_name == 'get_coin_price':
            ticker = parameters.get('ticker', 'KRW-BTC')
            result = get_coin_price_sync(ticker)
        elif tool_name == 'get_portfolio_status':
            user_id = parameters.get('user_id', 1)
            result = get_portfolio_status_sync(user_id)
        elif tool_name == 'analyze_trading_performance':
            user_id = parameters.get('user_id', 1)
            days = min(parameters.get('days', 7), 30)  # 최대 30일로 제한
            result = analyze_trading_performance_sync(user_id, days)
        elif tool_name == 'check_investment_recommendation':
            ticker = parameters.get('ticker', 'KRW-BTC')
            result = check_investment_recommendation_sync(ticker)
        else:
            return jsonify({"error": f"Unknown tool: {tool_name}"}), 400

        return jsonify({
            "result": result,
            "tool": tool_name,
            "parameters": parameters,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        import traceback
        error_details = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        return jsonify(error_details), 500


# 동기 버전의 함수들
def get_coin_price_sync(ticker: str) -> str:
    """동기 버전의 코인 가격 조회"""
    try:
        import pyupbit

        # 현재 가격 조회
        price_info = pyupbit.get_current_price(ticker)
        if price_info is None:
            return f"❌ {ticker}의 가격 정보를 찾을 수 없습니다."

        # 24시간 변동률 정보 조회
        try:
            ticker_info = pyupbit.get_tickers(fiat="KRW")
            if ticker not in ticker_info:
                return f"❌ {ticker}는 지원되지 않는 티커입니다."

            # 24시간 전 가격과 비교
            df = pyupbit.get_ohlcv(ticker, interval="day", count=2)
            if df is not None and len(df) >= 2:
                yesterday_close = df['close'].iloc[-2]
                change_rate = ((price_info - yesterday_close) / yesterday_close) * 100
                change_amount = price_info - yesterday_close
            else:
                change_rate = 0
                change_amount = 0

        except Exception:
            change_rate = 0
            change_amount = 0

        result = {
            "ticker": ticker,
            "current_price": f"{price_info:,}원",
            "change_amount": f"{change_amount:+,.0f}원",
            "change_rate": f"{change_rate:+.2f}%",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 가격 조회 중 오류가 발생했습니다: {str(e)}"


def get_portfolio_status_sync(user_id: int = 1) -> str:
    """동기 버전의 포트폴리오 상태 조회"""
    try:
        from app.models import User, TradingFavorite, TradeRecord
        from app import create_app, db

        # 새로운 앱 컨텍스트 생성하여 충돌 방지
        temp_app = create_app()
        with temp_app.app_context():
            user = User.query.get(user_id)
            if not user:
                return "❌ 사용자를 찾을 수 없습니다."

            active_strategies = TradingFavorite.query.filter_by(
                user_id=user_id,
                start_yn='Y'
            ).all()

            # 최근 24시간 매매 기록 조회
            yesterday = datetime.now() - timedelta(days=1)
            recent_trades = TradeRecord.query.filter(
                TradeRecord.user_id == user_id,
                TradeRecord.timestamp >= yesterday
            ).order_by(TradeRecord.timestamp.desc()).limit(10).all()

            result = {
                "user": user.username,
                "active_strategies": len(active_strategies),
                "strategy_details": [
                    {
                        "name": strategy.name,
                        "ticker": strategy.ticker,
                        "strategy": strategy.strategy,
                        "buy_amount": f"{strategy.buy_amount:,}원"
                    } for strategy in active_strategies
                ],
                "recent_trades_count": len(recent_trades),
                "recent_trades": [
                    {
                        "ticker": trade.ticker,
                        "type": trade.trade_type,
                        "price": f"{trade.price:,}원" if trade.price else "N/A",
                        "amount": f"{trade.amount:,}원" if trade.amount else "N/A",
                        "timestamp": trade.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    } for trade in recent_trades[:5]
                ]
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 포트폴리오 조회 중 오류가 발생했습니다: {str(e)}"


def analyze_trading_performance_sync(user_id: int = 1, days: int = 7) -> str:
    """동기 버전의 매매 성과 분석"""
    try:
        from app.models import User, TradeRecord
        from app import create_app

        temp_app = create_app()
        with temp_app.app_context():
            # 지정된 기간의 매매 기록 조회
            start_date = datetime.now() - timedelta(days=days)
            trades = TradeRecord.query.filter(
                TradeRecord.user_id == user_id,
                TradeRecord.timestamp >= start_date
            ).all()

            if not trades:
                return f"❌ 최근 {days}일 동안의 매매 기록이 없습니다."

            # 성과 분석
            buy_trades = [t for t in trades if t.trade_type == 'BUY']
            sell_trades = [t for t in trades if t.trade_type == 'SELL']

            total_buy_amount = sum(t.amount for t in buy_trades if t.amount)
            total_sell_amount = sum(t.amount for t in sell_trades if t.amount)

            profit_trades = [t for t in sell_trades if hasattr(t, 'profit_loss') and t.profit_loss and t.profit_loss > 0]
            loss_trades = [t for t in sell_trades if hasattr(t, 'profit_loss') and t.profit_loss and t.profit_loss < 0]

            # 가장 많이 거래한 코인 분석
            coin_counts = {}
            for trade in trades:
                coin_counts[trade.ticker] = coin_counts.get(trade.ticker, 0) + 1

            sorted_coins = sorted(coin_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            result = {
                "period": f"최근 {days}일",
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_trades": len(trades),
                "buy_count": len(buy_trades),
                "sell_count": len(sell_trades),
                "total_buy_amount": f"{total_buy_amount:,.0f}원",
                "total_sell_amount": f"{total_sell_amount:,.0f}원",
                "profit_trades": len(profit_trades),
                "loss_trades": len(loss_trades),
                "win_rate": f"{(len(profit_trades) / len(sell_trades) * 100):.1f}%" if sell_trades else "0%",
                "most_traded_coins": dict(sorted_coins)
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 성과 분석 중 오류가 발생했습니다: {str(e)}"


def check_investment_recommendation_sync(ticker: str) -> str:
    """동기 버전의 투자 추천 분석"""
    try:
        import pyupbit

        current_price = pyupbit.get_current_price(ticker)
        if current_price is None:
            return f"❌ {ticker}의 가격 정보를 찾을 수 없습니다."

        # 차트 데이터 조회 (최근 30일)
        df = pyupbit.get_ohlcv(ticker, interval="day", count=30)
        if df is None or df.empty:
            return f"❌ {ticker}의 차트 데이터를 가져올 수 없습니다."

        # 기술적 분석
        recent_high = df['high'].tail(7).max()
        recent_low = df['low'].tail(7).min()
        ma5 = df['close'].rolling(5).mean().iloc[-1]
        ma20 = df['close'].rolling(20).mean().iloc[-1]

        # 투자 신호 분석
        signals = []
        risk_level = "중간"

        if current_price > ma5 > ma20:
            signals.append("✅ 상승 추세")
            risk_level = "낮음"
        elif current_price < ma5 < ma20:
            signals.append("❌ 하락 추세")
            risk_level = "높음"
        else:
            signals.append("⚠️ 혼조세")

        # 현재 실행 중인 전략 확인
        try:
            from app.models import TradingFavorite
            from app import create_app

            temp_app = create_app()
            with temp_app.app_context():
                active_strategy = TradingFavorite.query.filter_by(
                    ticker=ticker,
                    start_yn='Y'
                ).first()

                strategy_info = {
                    "exists": active_strategy is not None,
                    "strategy_name": active_strategy.name if active_strategy else None,
                    "strategy_type": active_strategy.strategy if active_strategy else None
                }
        except Exception:
            strategy_info = {"exists": False}

        result = {
            "ticker": ticker,
            "current_price": f"{current_price:,}원",
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "technical_analysis": {
                "5_day_ma": f"{ma5:,.0f}원",
                "20_day_ma": f"{ma20:,.0f}원",
                "recent_high": f"{recent_high:,}원",
                "recent_low": f"{recent_low:,}원"
            },
            "investment_signals": signals,
            "risk_level": risk_level,
            "active_strategy": strategy_info,
            "recommendation": "추가 분석 필요" if risk_level == "중간" else
            ("투자 고려 가능" if risk_level == "낮음" else "투자 주의 필요")
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 투자 분석 중 오류가 발생했습니다: {str(e)}"


# 에러 핸들러 추가
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    print(f"MCP 웹 서버 시작...")
    print(f"호스트: {Config.MCP_SERVER_HOST}")
    print(f"포트: {Config.MCP_SERVER_PORT}")
    print(f"인증 토큰: {Config.MCP_AUTH_TOKEN[:10]}...")

    socketio.run(
        app,
        host=Config.MCP_SERVER_HOST,
        port=Config.MCP_SERVER_PORT,
        debug=False,
        allow_unsafe_werkzeug=True  # 개발 환경에서만
    )