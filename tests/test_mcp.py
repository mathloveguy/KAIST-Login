import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio_handshake_and_bounded_tool_schema():
    params = StdioServerParameters(command=sys.executable, args=["-m", "kaist_login", "serve"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result = await client.list_tools()
            assert {tool.name for tool in result.tools} == {"kaist_status", "kaist_login", "kaist_read_page"}
            for tool in result.tools:
                assert not {"password", "otp", "javascript", "cookie", "token"} & set(tool.inputSchema.get("properties", {}))
