"""
jobsearch-mcp: Multi-source job search MCP server
Transport: Streamable HTTP (FastMCP)
User context via X-User-ID header injected by LibreChat
"""

import os
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .db import init_db
from .tools.jobs import register_tools as register_job_tools
from .tools.tracking import register_tools as register_tracking_tools
from .tools.scoring import register_tools as register_scoring_tools
from .tools.profile import register_tools as register_profile_tools


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


mcp = FastMCP("jobsearch", lifespan=lifespan)

register_job_tools(mcp)
register_tracking_tools(mcp)
register_scoring_tools(mcp)
register_profile_tools(mcp)


if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8383"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
