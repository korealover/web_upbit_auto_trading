
# mcp_proxy.py - 로컬에서 실행하는 프록시 스크립트
import asyncio
import json
import requests
import sys
from typing import Any
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# 외부 서버 URL
SERVER_URL = "http://jhsun.cafe24.com:5001"
# 인증 토큰 - Config에서 가져오는 것이 좋지만 일단 하드코딩
AUTH_TOKEN = "mcp-auth-token-2025"  # Config.MCP_AUTH_TOKEN과 같은 값

server = Server("upbit-trading-remote")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """외부 서버에서 도구 목록 가져오기"""
    try:
        response = requests.get(f"{SERVER_URL}/mcp/tools", timeout=10)
        if response.status_code == 200:
            tools_data = response.json()

            tools = []
            for tool in tools_data["tools"]:
                # MCP Tool 객체로 변환
                input_schema = {
                    "type": "object",
                    "properties": {},
                    "required": []
                }

                for param_name, param_info in tool["parameters"].items():
                    input_schema["properties"][param_name] = {
                        "type": param_info["type"],
                        "description": param_info["description"]
                    }
                    if param_info.get("required"):
                        input_schema["required"].append(param_name)

                tools.append(types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    inputSchema=input_schema
                ))

            return tools
    except Exception as e:
        print(f"Error fetching tools: {e}", file=sys.stderr)
        return []

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent]:
    """외부 서버로 도구 실행 요청 전달 (인증 포함)"""
    try:
        payload = {
            "tool": name,
            "parameters": arguments or {}
        }

        headers = {
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{SERVER_URL}/mcp/execute",
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            return [types.TextContent(type="text", text=result["result"])]
        elif response.status_code == 401:
            return [types.TextContent(type="text", text="❌ 인증 실패: 토큰을 확인해주세요")]
        else:
            error_msg = response.json().get("error", "Unknown error")
            return [types.TextContent(type="text", text=f"❌ 서버 오류 ({response.status_code}): {error_msg}")]

    except requests.exceptions.Timeout:
        return [types.TextContent(type="text", text="❌ 서버 응답 시간 초과")]
    except requests.exceptions.ConnectionError:
        return [types.TextContent(type="text", text="❌ 서버에 연결할 수 없습니다")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"❌ 연결 오류: {str(e)}")]

async def main():
    """Run the MCP proxy server."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="upbit-trading-remote",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    print("Starting MCP proxy server...", file=sys.stderr)
    print(f"Connecting to: {SERVER_URL}", file=sys.stderr)
    asyncio.run(main())