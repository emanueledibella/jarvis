import os

from fastmcp import FastMCP

mcp = FastMCP("Jarvis subprocess fixture")


@mcp.tool
def environment_check() -> dict:
    return {
        "explicit_value": os.getenv("JARVIS_TEST_VALUE"),
        "provider_key_present": bool(os.getenv("OPENAI_API_KEY")),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
