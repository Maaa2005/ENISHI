import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_stdio_mcp_starts_without_desktop(tmp_path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "ENISHI_DATA_DIR": str(tmp_path / "data"),
            "ENISHI_CACHE_DIR": str(tmp_path / "cache"),
            "ENISHI_LOG_DIR": str(tmp_path / "logs"),
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "enishi_core.mcp_server"],
        env=environment,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
    assert {tool.name for tool in tools.tools} == {
        "search_memories",
        "remember",
        "record_decision",
    }
