import asyncio
import os
import queue
import sys
import threading

from mcp import Client, StdioServerParameters
from mcp.types import TextContent


class MCPClient:
    def __init__(self):
        project_dir = os.path.dirname(os.path.abspath(__file__))
        self.server = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(project_dir, "tools.py")],
            cwd=project_dir,
        )
        self._jobs = queue.Queue()
        self._thread = None
        self._error = None

    def connect(self):
        ready = threading.Event()
        self._error = None
        self._thread = threading.Thread(
            target=self._run_session,
            args=(ready,),
            daemon=True,
        )
        self._thread.start()
        ready.wait()
        if self._error is not None:
            raise self._error

    def get_tools_json(self):
        return self._ask("list_tools", None)

    def call_tool(self, name, arguments):
        return self._ask("call_tool", (name, arguments))

    def close(self):
        self._jobs.put(None)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _ask(self, kind, payload):
        reply = queue.Queue()
        self._jobs.put((kind, payload, reply))
        result = reply.get()
        if isinstance(result, Exception):
            raise result
        return result

    def _run_session(self, ready):
        asyncio.run(self._session(ready))

    async def _session(self, ready):
        try:
            async with Client(self.server) as client:
                ready.set()
                loop = asyncio.get_running_loop()
                while True:
                    job = await loop.run_in_executor(None, self._jobs.get)
                    if job is None:
                        break
                    kind, payload, reply = job
                    try:
                        if kind == "list_tools":
                            reply.put(await self._list_tools(client))
                        elif kind == "call_tool":
                            name, arguments = payload
                            reply.put(await self._call_tool(client, name, arguments))
                        else:
                            reply.put(ValueError(f"Unknown MCP job: {kind}"))
                    except Exception as exc:
                        reply.put(exc)
        except Exception as exc:
            self._error = exc
            ready.set()

    async def _list_tools(self, client):
        listed = await client.list_tools()
        tools_json = []
        for tool in listed.tools:
            tools_json.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                }
            )
        return tools_json

    async def _call_tool(self, client, name, arguments):
        result = await client.call_tool(name, arguments)
        parts = []
        for block in result.content:
            if isinstance(block, TextContent):
                parts.append(block.text)
        return "\n".join(parts)
