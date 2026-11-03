"""Synthetic services; never imports owner configuration or controls real devices."""
from fastmcp import FastMCP


def create_server():
    server = FastMCP("Jarvis synthetic assistant integrations")
    state = {"on": False}

    @server.tool(name="GetLiveContext")
    def live_context() -> dict:
        return {"entities": [{"entity_id": "light.fixture", "name": "Fixture desk", "state": "on" if state["on"] else "off"}]}

    @server.tool(name="HassGetState")
    def get_state(name: str) -> dict:
        return {"name": name, "state": "on" if state["on"] else "off"}

    @server.tool(name="HassTurnOn")
    def turn_on(name: str) -> dict:
        state["on"] = True
        return {"accepted": True, "name": name}

    @server.tool(name="UnexpectedTool")
    def unexpected_tool(value: str = "") -> dict:
        return {"synthetic": value}

    @server.tool(name="searchJiraIssuesUsingJql")
    def search_jira(cloudId: str, jql: str, maxResults: int = 10, fields: list[str] | None = None, nextPageToken: str = "") -> dict:
        if cloudId != "https://teamsystem.atlassian.net/" or maxResults != 10:
            raise ValueError("Synthetic tenant and page limit are required.")
        return {"issues": [{"key": "BVTL-1", "fields": {"summary": "Synthetic integration task", "status": {"name": "In Progress"}, "updated": "2026-10-30T09:00:00+01:00", "description": "Synthetic source; no real project data."}}], "isLast": True}

    @server.tool(name="getJiraIssue")
    def get_issue(cloudId: str, issueIdOrKey: str) -> dict:
        return {"key": issueIdOrKey, "fields": {"summary": "Synthetic issue", "status": {"name": "Open"}, "description": "Synthetic requirements only."}}

    return server


if __name__ == "__main__":
    create_server().run(transport="http", host="127.0.0.1", port=8790, show_banner=False)
