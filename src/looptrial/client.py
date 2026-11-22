"""Standalone MCP SDK example. Only the subprocess knows LoopTrial internals."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def session(args):
    env = os.environ.copy()
    server = StdioServerParameters(command=sys.executable, args=["-m", "looptrial.server"], env=env)
    async with stdio_client(server) as (reader, writer), ClientSession(reader, writer) as client:
        await client.initialize()
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]

        async def invoke(name, arguments):
            result = await client.call_tool(name, arguments)
            if result.isError:
                raise RuntimeError(result.content[0].text)
            parts = [json.loads(item.text) for item in result.content if item.type == "text"]
            if name in ("list_runs", "parameter_history"):
                return parts
            return parts[0] if len(parts) == 1 else parts

        if args.list:
            return [t.model_dump(exclude_none=True) for t in tools.tools]
        if args.tool:
            return await invoke(args.tool, json.loads(args.arguments.read_text(encoding="utf-8-sig")) if args.arguments else {})
        info = await invoke("describe", {"uri":"sim://thermal"})
        run = await invoke("run_experiment", {"uri":"sim://thermal", "action":"step", "conditions":{"target_c":50}})
        fetched = await invoke("get_run", {"run_id":run["id"]})
        verified = await invoke("review", {"record":run["id"]})
        if fetched["status"] != "completed" or not verified["recomputed"]:
            raise RuntimeError("sample acquisition or offline verification failed")
        return {"tools": names, "device": info["id"], "run": fetched, "review": verified}


def main():
    cli = argparse.ArgumentParser(description="Independent stdio MCP client. With no options, discover, acquire, fetch and review a thermal trace.")
    cli.add_argument("--list", action="store_true", help="print discovered tool schemas")
    cli.add_argument("--tool", help="invoke a named tool")
    cli.add_argument("--arguments", type=Path, help="UTF-8 JSON object file for the tool")
    result = asyncio.run(session(cli.parse_args()))
    print(json.dumps(result, ensure_ascii=True))
    return int(isinstance(result, dict) and (result.get("ok") is False or result.get("status") == "failed"))


if __name__ == "__main__":
    sys.exit(main())
