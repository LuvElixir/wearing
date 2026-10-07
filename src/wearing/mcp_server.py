"""Small registration shim for official MCP SDK 1.x and Hermes SDK 2.x.

Only callback registration differs; wire messages remain the standard MCP types.
"""
from types import SimpleNamespace
from mcp.server.lowlevel import Server


def create_server(name, list_tools, call_tool):
    try:
        return Server(name,on_list_tools=list_tools,on_call_tool=call_tool)
    except TypeError:
        server=Server(name)
        @server.list_tools()
        async def tools():
            return (await list_tools(server.request_context,None)).tools
        @server.call_tool()
        async def call(name,arguments):
            return await call_tool(server.request_context,SimpleNamespace(name=name,arguments=arguments))
        return server
