"""Stdio MCP tools for a user's existing agent."""

import asyncio

from mcp.server.fastmcp import FastMCP

from . import engine

mcp = FastMCP("LoopTrial", instructions=(
    "Use existing conversation conditions and discover the selected device. Read effective parameters. "
    "A diagnosis may require only one capture. Before tuning, record a baseline and select bounded goals, "
    "constraints, repeat conditions and a budget. Apply only declared temporary parameters. Inspect each "
    "response and verify any restoration. Confirm a passing candidate in fresh runs with new IDs."
))


async def call(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except engine.OPERATION_ERRORS as error:
        return engine.failure(error)


@mcp.tool()
async def devices():
    """List simulated devices, serial candidates and the BLE preset. Use describe to handshake."""
    return await call(engine.devices)


@mcp.tool()
async def describe(uri: str):
    """Discover firmware identity, signal units, parameters, permitted actions, conditions and metrics."""
    return await call(engine.describe, uri)


@mcp.tool()
async def read_parameters(uri: str):
    """Read back the device's current effective values."""
    return await call(engine.read_parameters, uri)


@mcp.tool()
async def apply_parameters(uri: str, values: dict[str, float]):
    """Apply bounded temporary values and read back. Returns previous, applied and independently verified values."""
    return await call(engine.apply_parameters, uri, values)


@mcp.tool()
async def parameter_history(uri: str, limit: int = 20):
    """Retrieve write and recovery receipts, newest first."""
    return await call(engine.writes, uri, limit)


@mcp.tool()
async def run_experiment(uri: str, action: str, conditions: dict[str, float] | None = None,
                   goals: dict[str, dict[str, float]] | None = None,
                   constraints: dict[str, dict[str, float]] | None = None,
                   note: str = "", key: str | None = None, background: bool = False,
                   pace: float = 0, fault: str | None = None):
    """Acquire one declared action, with optional metric bounds {name: {le: max, ge: min}}.
    Returns ID, conditions, effective config, metrics, checks and record path. A completed run can miss goals.
    Reuse a key for retries, use a new key for a fresh trial. Background runs survive client exit.
    Simulator-only pace delays acquisition by 0..600 seconds; fault='sample_gap' truncates a trace.
    """
    return await call(engine.run_experiment, uri, action, conditions, goals, constraints, note, key, background, pace, fault)


@mcp.tool()
async def get_run(run_id: str):
    """Get current status, terminal reason or measured result by run ID."""
    return await call(engine.get_run, run_id)


@mcp.tool()
async def cancel_run(run_id: str):
    """Request cancellation, then poll get_run until terminal to learn the last confirmed state."""
    return await call(engine.cancel_run, run_id)


@mcp.tool()
async def list_runs(limit: int = 20):
    """List recent IDs and verdicts in this store, most recent first (limit 1..200)."""
    return await call(engine.list_runs, limit)


@mcp.tool()
async def waveform(run_id: str, start: int = 0, count: int = 8):
    """Get 1..200 raw samples by offset, including timestamps. Also accepts a portable record path."""
    return await call(engine.waveform, run_id, start, count)


@mcp.tool()
async def review(record: str):
    """Offline checksum verification and metric recomputation from run ID, directory or record.json."""
    return await call(engine.review, record)


@mcp.tool()
async def compare(first: str, second: str):
    """Compare metrics of two completed experiments with matching device, version, action and conditions."""
    return await call(engine.compare, first, second)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
