import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_control_plane_exposes_requests_but_not_human_authority(tmp_path) -> None:
    environment = os.environ.copy()
    environment["ENISHI_CORE_INFO_PATH"] = str(tmp_path / "not-running.json")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "enishi_mcp.server"],
        env=environment,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            unavailable = await session.call_tool("list_peers", {})
    names = {tool.name for tool in tools.tools}
    assert names == {
        "list_peers",
        "list_negotiations",
        "get_negotiation",
        "get_my_card",
        "create_request",
        "add_peer_from_card",
    }
    assert not names.intersection({"approve", "trust_peer", "change_disclosure"})
    assert "起動していません" in str(unavailable.content)
