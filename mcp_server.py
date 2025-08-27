# mcp_server.py
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Sequence

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# MCP imports
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Your app imports
from app.models import User, TradeRecord, TradingFavorite
from app import create_app, db
import pyupbit

# Initialize Flask app globally
app = create_app(enable_scheduler=False)

# Create MCP server instance
server = Server("upbit-trading-analysis")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="get_coin_price",
            description="특정 가상화폐의 현재 가격 정보를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "가상화폐 티커 (예: KRW-BTC, KRW-ETH)",
                    }
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get_portfolio_status",
            description="사용자의 현재 포트폴리오 상태를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "사용자 ID",
                        "default": 1,
                    }
                },
                "required": [],
            },
        ),
        types.Tool(
            name="analyze_trading_performance",
            description="특정 기간 동안의 매매 성과를 분석합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer",
                        "description": "사용자 ID",
                        "default": 1,
                    },
                    "days": {
                        "type": "integer",
                        "description": "분석할 일수",
                        "default": 7,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="check_investment_recommendation",
            description="특정 가상화폐의 투자 여부를 분석하여 추천합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "가상화폐 티커 (예: KRW-BTC, KRW-ETH)",
                    }
                },
                "required": ["ticker"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent]:
    """Handle tool calls."""

    if name == "get_coin_price":
        ticker = arguments.get("ticker") if arguments else "KRW-BTC"
        result = await get_coin_price(ticker)
        return [types.TextContent(type="text", text=result)]

    elif name == "get_portfolio_status":
        user_id = arguments.get("user_id", 1) if arguments else 1
        result = await get_portfolio_status(user_id)
        return [types.TextContent(type="text", text=result)]

    elif name == "analyze_trading_performance":
        user_id = arguments.get("user_id", 1) if arguments else 1
        days = arguments.get("days", 7) if arguments else 7
        result = await analyze_trading_performance(user_id, days)
        return [types.TextContent(type="text", text=result)]

    elif name == "check_investment_recommendation":
        ticker = arguments.get("ticker") if arguments else "KRW-BTC"
        result = await check_investment_recommendation(ticker)
        return [types.TextContent(type="text", text=result)]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def get_coin_price(ticker: str) -> str:
    """특정 가상화폐의 현재 가격 정보를 조회합니다."""
    try:
        # 업비트 API를 통해 현재 가격 조회
        price_info = pyupbit.get_current_price(ticker)

        if price_info is None:
            return f"❌ {ticker}의 가격 정보를 찾을 수 없습니다."

        # 추가 정보 조회
        try:
            orderbook = pyupbit.get_orderbook(ticker)
            volume_24h = pyupbit.get_ohlcv(ticker, interval="minute1", count=1440)
            if volume_24h is not None and not volume_24h.empty:
                volume_24h_total = volume_24h['volume'].sum()
            else:
                volume_24h_total = 0
        except Exception:
            volume_24h_total = 0

        result = {
            "ticker": ticker,
            "current_price": f"{price_info:,}원",
            "volume_24h": f"{volume_24h_total:,.0f}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 가격 조회 중 오류가 발생했습니다: {str(e)}"


async def get_portfolio_status(user_id: int = 1) -> str:
    """사용자의 현재 포트폴리오 상태를 조회합니다."""
    try:
        with app.app_context():
            # 사용자 정보 조회
            user = User.query.get(user_id)
            if not user:
                return "❌ 사용자를 찾을 수 없습니다."

            # 활성화된 매매 전략 조회
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
                        "price": f"{trade.price:,}원",
                        "amount": f"{trade.amount:,}원",
                        "timestamp": trade.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    } for trade in recent_trades[:5]  # 최근 5개만 표시
                ]
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 포트폴리오 조회 중 오류가 발생했습니다: {str(e)}"


async def analyze_trading_performance(user_id: int = 1, days: int = 7) -> str:
    """특정 기간 동안의 매매 성과를 분석합니다."""
    try:
        with app.app_context():
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

            total_buy_amount = sum(t.amount for t in buy_trades)
            total_sell_amount = sum(t.amount for t in sell_trades)

            profit_trades = [t for t in sell_trades if hasattr(t, 'profit_loss') and t.profit_loss and t.profit_loss > 0]
            loss_trades = [t for t in sell_trades if hasattr(t, 'profit_loss') and t.profit_loss and t.profit_loss < 0]

            result = {
                "period": f"최근 {days}일",
                "total_trades": len(trades),
                "buy_count": len(buy_trades),
                "sell_count": len(sell_trades),
                "total_buy_amount": f"{total_buy_amount:,.0f}원",
                "total_sell_amount": f"{total_sell_amount:,.0f}원",
                "profit_trades": len(profit_trades),
                "loss_trades": len(loss_trades),
                "win_rate": f"{(len(profit_trades) / len(sell_trades) * 100):.1f}%" if sell_trades else "0%",
                "most_traded_coins": {}
            }

            # 가장 많이 거래한 코인 분석
            coin_counts = {}
            for trade in trades:
                coin_counts[trade.ticker] = coin_counts.get(trade.ticker, 0) + 1

            sorted_coins = sorted(coin_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            result["most_traded_coins"] = {coin: count for coin, count in sorted_coins}

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 성과 분석 중 오류가 발생했습니다: {str(e)}"


async def check_investment_recommendation(ticker: str) -> str:
    """특정 가상화폐의 투자 여부를 분석하여 추천합니다."""
    try:
        with app.app_context():
            # 현재 가격 정보 조회
            current_price = pyupbit.get_current_price(ticker)
            if current_price is None:
                return f"❌ {ticker}의 가격 정보를 찾을 수 없습니다."

            # 차트 데이터 조회 (최근 30일)
            df = pyupbit.get_ohlcv(ticker, interval="day", count=30)
            if df is None or df.empty:
                return f"❌ {ticker}의 차트 데이터를 가져올 수 없습니다."

            # 기술적 분석
            recent_high = df['high'].tail(7).max()  # 최근 7일 최고가
            recent_low = df['low'].tail(7).min()  # 최근 7일 최저가
            avg_volume = df['volume'].tail(7).mean()  # 최근 7일 평균 거래량
            current_volume = df['volume'].iloc[-1]  # 오늘 거래량

            # 이동평균선 계산
            ma5 = df['close'].rolling(5).mean().iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]

            # 투자 신호 분석
            signals = []
            risk_level = "중간"

            if current_price > ma5 > ma20:
                signals.append("✅ 상승 추세 (가격 > 5일선 > 20일선)")
                risk_level = "낮음"
            elif current_price < ma5 < ma20:
                signals.append("❌ 하락 추세 (가격 < 5일선 < 20일선)")
                risk_level = "높음"
            else:
                signals.append("⚠️ 혼조세 (추세 불분명)")

            if current_volume > avg_volume * 1.5:
                signals.append("📈 거래량 급증 (평균 대비 50% 이상)")
            elif current_volume < avg_volume * 0.5:
                signals.append("📉 거래량 부족 (평균 대비 50% 미만)")

            # 가격 위치 분석
            price_position = (current_price - recent_low) / (recent_high - recent_low) * 100
            if price_position > 80:
                signals.append("⚠️ 고점권 진입 (최근 7일 고점 대비 80% 이상)")
            elif price_position < 20:
                signals.append("💡 저점권 진입 (최근 7일 저점 대비 20% 이하)")

            # 현재 실행 중인 전략이 있는지 확인
            active_strategy = TradingFavorite.query.filter_by(
                ticker=ticker,
                start_yn='Y'
            ).first()

            result = {
                "ticker": ticker,
                "current_price": f"{current_price:,}원",
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "technical_analysis": {
                    "5_day_ma": f"{ma5:,.0f}원",
                    "20_day_ma": f"{ma20:,.0f}원",
                    "recent_high": f"{recent_high:,}원",
                    "recent_low": f"{recent_low:,}원",
                    "price_position": f"{price_position:.1f}%",
                    "volume_ratio": f"{(current_volume / avg_volume):.1f}배"
                },
                "investment_signals": signals,
                "risk_level": risk_level,
                "active_strategy": {
                    "exists": active_strategy is not None,
                    "strategy_name": active_strategy.name if active_strategy else None,
                    "strategy_type": active_strategy.strategy if active_strategy else None
                } if active_strategy else {"exists": False},
                "recommendation": "추가 분석 필요" if risk_level == "중간" else
                ("투자 고려 가능" if risk_level == "낮음" else "투자 주의 필요")
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ 투자 분석 중 오류가 발생했습니다: {str(e)}"


async def main():
    """Run the MCP server."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="upbit-trading-analysis",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())