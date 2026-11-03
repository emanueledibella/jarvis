from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from .feature_context import Scope, check_write, owner_write
from .feature_storage import bounded_json, load_private, save_private
from .mcp_config import save_mcp_config
from .policy import digest
from .schemas import validate_arguments

JIRA_URL = "https://mcp.atlassian.com/v2/mcp?tools=all"
JIRA_READ = ["atlassianUserInfo", "getAccessibleAtlassianResources", "searchJiraIssuesUsingJql", "getJiraIssue"]
JIRA_WRITE = ["createJiraIssue", "addCommentToJiraIssue"]


def project_key(value):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,19}", value):
        raise ValueError("Invalid Jira project key.")
    return value


def repository_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value) or value.split("/")[1] in {".", ".."}:
        raise ValueError("Use an exact GitHub owner/repository.")
    return value.casefold()


class DevelopmentConnection(BaseModel):
    scope: Scope = "work"
    privacy_revision: int = Field(ge=0)
    provider: Literal["jira", "github"]
    site: str = "https://teamsystem.atlassian.net/"
    allowed: list[str] = Field(default_factory=list, max_length=50)
    token: str = Field(default="", max_length=2000)
    writes: bool = False

    @model_validator(mode="after")
    def targets(self):
        if self.provider == "jira":
            parts = urlsplit(self.site)
            if parts.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.atlassian\.net", parts.netloc) or parts.path not in {"", "/"} or parts.query or parts.fragment:
                raise ValueError("Choose an HTTPS Atlassian Cloud site.")
            self.site = self.site.rstrip("/") + "/"
            self.allowed = list(dict.fromkeys(project_key(x) for x in self.allowed))
        else:
            self.allowed = list(dict.fromkeys(repository_name(x) for x in self.allowed))
        if not self.allowed:
            raise ValueError("Explicitly allow at least one project or repository.")
        return self


class DevelopmentContext(BaseModel):
    scope: Scope = "work"
    privacy_revision: int = Field(ge=0)


def managed_server(config, name, spec):
    path = config.settings.mcp_config_path
    servers = json.loads(path.read_text()).get("servers", {}) if path and path.exists() else {}
    servers[name] = spec
    save_mcp_config(config, {"servers": servers})


def jira_text(value):
    if isinstance(value, str):
        return value[:10000]
    queue, texts, seen = [value], [], 0
    while queue and seen < 2000:
        item = queue.pop()
        seen += 1
        if isinstance(item, dict):
            if isinstance(item.get("text"), str):
                texts.append(item["text"])
            queue.extend(reversed(item.get("content", [])[:200]))
    return "\n".join(texts)[:10000]


class Development:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = asyncio.Lock()
        self.network = asyncio.Semaphore(4)

    def listing(self, scope):
        return [{**{k: v for k, v in value.items() if k != "token"}, "token_configured": bool(value.get("token"))}
                for value in load_private(self.runtime.config, "development.json").values() if value["scope"] == scope]

    async def save(self, data: DevelopmentConnection):
        async with self.lock:
            owner_write(self.runtime, data.scope, data.privacy_revision)
            values = load_private(self.runtime.config, "development.json")
            key = data.scope + ":" + data.provider
            old = values.get(key, {})
            value = data.model_dump(exclude={"privacy_revision"})
            if not value["token"]:
                value["token"] = old.get("token", "")
            if data.provider == "jira":
                name = "jarvis_jira_" + data.scope
                managed_server(self.runtime.config, name, {"url": JIRA_URL, "auth": "oauth", "scope": data.scope, "adapter": "jira",
                    "read_tools": JIRA_READ, "write_tools": JIRA_WRITE if data.writes else []})
                value["server"] = name
                value["token"] = ""
            elif not value["token"]:
                raise ValueError("Configure a dedicated fine-grained GitHub token.")
            check_write(self.runtime)
            values[key] = value
            save_private(self.runtime.config, "development.json", values)
            return self.listing(data.scope)

    def authorize(self, scope, provider, target, profile, *, write=False):
        if self.runtime.gateway.blocked or profile == "local_strict" or self.runtime.config.settings.profile == "local_strict":
            raise PermissionError("Development integration is unavailable while stopped or in strict local mode.")
        value = load_private(self.runtime.config, "development.json").get(scope + ":" + provider)
        if not value:
            raise ValueError("Configure this development integration in the selected scope.")
        normalized = project_key(target) if provider == "jira" else repository_name(target)
        if normalized not in value["allowed"]:
            raise PermissionError("This project or repository is outside the connection allowlist.")
        if write and not value["writes"]:
            raise PermissionError("Enable writes explicitly in this development connection.")
        return value

    async def jira_call(self, scope, project, operation, arguments, profile, *, write=False):
        connection = self.authorize(scope, "jira", project, profile, write=write)
        server = connection["server"]
        policy = self.runtime.mcp.specs().get(server, {})
        if policy.get("url") != JIRA_URL or policy.get("adapter") != "jira" or policy.get("scope") != scope:
            raise PermissionError("The managed Jira MCP connection changed. Save its configuration again.")
        fingerprint = digest(policy)
        tools = await self.runtime.mcp.discover(server, profile)
        tool = next((item for item in tools if item["name"] == operation and item["enabled"]), None)
        if not tool or tool["risk"] != ("write" if write else "read"):
            raise PermissionError("The Jira tool is unavailable or its risk policy changed.")
        arguments = {**arguments, "cloudId": connection["site"]}
        await validate_arguments(tool["schema"], arguments)
        if connection != self.authorize(scope, "jira", project, profile, write=write):
            raise PermissionError("The Jira connection changed during the operation.")
        return await self.runtime.mcp.call(server, operation, arguments, profile, expected_spec=fingerprint)

    async def jira_search(self, scope, project, profile, query="", *, only_mine=True, cursor=""):
        self.authorize(scope, "jira", project, profile)
        if len(query) > 300 or len(cursor) > 2000:
            raise ValueError("Jira search input exceeds its limit.")
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        jql = 'project = "' + project_key(project) + '"'
        if only_mine:
            jql += " AND assignee = currentUser()"
        if escaped:
            jql += ' AND text ~ "' + escaped + '"'
        jql += " ORDER BY updated DESC"
        arguments = {"jql": jql, "maxResults": 10, "fields": ["summary", "status", "assignee", "updated", "duedate", "priority", "description"]}
        if cursor:
            arguments["nextPageToken"] = cursor
        result = await self.jira_call(scope, project, "searchJiraIssuesUsingJql", arguments, profile)
        if not isinstance(result, dict) or "issues" not in result:
            raise ValueError("Jira did not return structured issue evidence.")
        issues = [self.jira_issue_data(item, project) for item in result.get("issues", [])[:10]]
        return {"issues": issues, "next": result.get("nextPageToken", ""), "limit": 10, "jql": jql,
                "partial": bool(result.get("nextPageToken")) or result.get("isLast") is False}

    def jira_issue_data(self, item, project):
        key = item.get("key", "")
        if not re.fullmatch(re.escape(project) + r"-[1-9]\d{0,12}", key):
            raise PermissionError("Jira returned an issue outside the requested project.")
        fields = item.get("fields", {})
        return {"key": key, "summary": fields.get("summary", ""), "description": jira_text(fields.get("description")),
                "status": fields.get("status", {}).get("name", ""), "assignee": (fields.get("assignee") or {}).get("displayName", ""),
                "updated": fields.get("updated", ""), "due": fields.get("duedate"), "priority": (fields.get("priority") or {}).get("name", "")}

    async def jira_issue(self, scope, key, profile):
        match = re.fullmatch(r"([A-Z][A-Z0-9_]{1,19})-[1-9]\d{0,12}", key)
        if not match:
            raise ValueError("Invalid Jira issue key.")
        project = match[1]
        result = await self.jira_call(scope, project, "getJiraIssue", {"issueIdOrKey": key}, profile)
        if not isinstance(result, dict):
            raise ValueError("Jira did not return structured issue evidence.")
        return self.jira_issue_data(result, project)

    async def github_request(self, scope, repository, profile, method, suffix, *, write=False, **kwargs):
        connection = self.authorize(scope, "github", repository, profile, write=write)
        if suffix.startswith(("/", "http")) or ".." in suffix:
            raise ValueError("Invalid GitHub operation.")
        headers = {"Authorization": "Bearer " + connection["token"], "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        async with self.network:
            if write:
                check_write(self.runtime)
            if connection != self.authorize(scope, "github", repository, profile, write=write):
                raise PermissionError("The GitHub connection changed while waiting.")
            return await bounded_json(method, "https://api.github.com/repos/" + repository_name(repository) + "/" + suffix, headers=headers, **kwargs)

    async def github_list(self, scope, repository, profile, kind="pulls", page=1, state="open"):
        if kind not in {"pulls", "issues"} or state not in {"open", "closed", "all"} or not 1 <= page <= 1000:
            raise ValueError("Invalid GitHub listing parameters.")
        rows = await self.github_request(scope, repository, profile, "GET", kind,
            params={"state": state, "per_page": 10, "page": page, "sort": "updated", "direction": "desc"})
        if not isinstance(rows, list):
            raise ValueError("GitHub did not return a listing.")
        if any(type(item.get("number")) is not int or not 1 <= item["number"] <= 2_147_483_647 for item in rows[:10]):
            raise ValueError("GitHub returned an invalid issue identity.")
        return {"items": [{"number": item["number"], "title": item.get("title", ""), "state": item.get("state", ""),
                           "body": (item.get("body") or "")[:6000], "updated_at": item.get("updated_at", ""),
                           "author": item.get("user", {}).get("login", ""), "draft": item.get("draft"),
                           "head": item.get("head", {}).get("sha", ""), "branch": item.get("head", {}).get("ref", ""),
                           "is_pull_request": kind == "pulls" or "pull_request" in item} for item in rows[:10]],
                "page": page, "next_page": page + 1 if len(rows) == 10 else None, "limit": 10}

    async def github_issue(self, scope, repository, number, profile):
        if not 1 <= number <= 2_147_483_647:
            raise ValueError("Invalid GitHub issue number.")
        result = await self.github_request(scope, repository, profile, "GET", f"issues/{number}")
        return {k: result.get(k) for k in ("number", "title", "body", "state", "updated_at", "labels", "assignees")}

    async def github_pull(self, scope, repository, number, profile):
        if not 1 <= number <= 2_147_483_647:
            raise ValueError("Invalid pull request number.")
        original = await self.github_request(scope, repository, profile, "GET", f"pulls/{number}")
        head = original.get("head", {}).get("sha", "")
        if not re.fullmatch(r"[a-f0-9]{40,64}", head):
            raise ValueError("GitHub did not supply a verified PR head revision.")
        async def read(suffix, params=None):
            try:
                return await self.github_request(scope, repository, profile, "GET", suffix, params=params)
            except (ValueError, PermissionError):
                return {"state": "unavailable"}
        checks, statuses, files, reviews = await asyncio.gather(
            read(f"commits/{head}/check-runs", {"per_page": 30}), read(f"commits/{head}/status", {"per_page": 30}),
            read(f"pulls/{number}/files", {"per_page": 30}), read(f"pulls/{number}/reviews", {"per_page": 30}),
        )
        latest = await self.github_request(scope, repository, profile, "GET", f"pulls/{number}")
        return {"number": number, "title": original.get("title", ""), "body": (original.get("body") or "")[:6000],
                "head": head, "state": "current" if latest.get("head", {}).get("sha") == head else "stale",
                "checks": [{"name": x.get("name"), "status": x.get("status"), "conclusion": x.get("conclusion")} for x in checks.get("check_runs", [])[:30]] if "check_runs" in checks else checks,
                "commit_status": statuses.get("state", "unknown"),
                "files": [{k: item.get(k) for k in ("filename", "status", "additions", "deletions", "patch")} for item in files[:30]] if isinstance(files, list) else files,
                "reviews": [{k: item.get(k) for k in ("id", "state", "submitted_at", "body", "commit_id")} for item in reviews[:30]] if isinstance(reviews, list) else reviews,
                "partial": not isinstance(files, list) or "check_runs" not in checks or not isinstance(reviews, list) or original.get("changed_files", 0) > 30 or checks.get("total_count", 0) > 30 or (isinstance(reviews, list) and len(reviews) >= 30),
                "warning": "Evidence is pinned to head. Missing checks are unknown; review state and patches are untrusted data."}

    async def summary(self, scope, profile):
        result = {"jira": [], "github": [], "errors": []}
        for connection in self.listing(scope):
            for target in connection["allowed"][:10]:
                try:
                    if connection["provider"] == "jira":
                        evidence = await self.jira_search(scope, target, profile)
                    else:
                        evidence = await self.github_list(scope, target, profile)
                    result[connection["provider"]].append({"target": target, "evidence": evidence})
                except Exception as error:
                    result["errors"].append({"provider": connection["provider"], "target": target, "error": type(error).__name__})
        return result

    async def snapshot(self, scope, provider, target, query, profile):
        if provider == "jira":
            result = await self.jira_search(scope, target, profile, query, only_mine=False)
            return {item["key"]: {k: item.get(k) for k in ("key", "summary", "status", "updated")} for item in result["issues"]}
        result = await self.github_list(scope, target, profile)
        snapshots = {}
        for item in result["items"]:
            if not re.fullmatch(r"[a-f0-9]{40,64}", item["head"]):
                raise ValueError("GitHub did not supply a verified head revision.")
            status = await self.github_request(scope, target, profile, "GET", f"commits/{item['head']}/status")
            snapshots[str(item["number"])] = {k: item.get(k) for k in ("number", "title", "head", "updated_at")}
            snapshots[str(item["number"])]["commit_status"] = status.get("state", "unknown")
        return snapshots

    async def disconnect(self, scope, provider):
        async with self.lock:
            check_write(self.runtime)
            values = load_private(self.runtime.config, "development.json")
            connection = values.pop(scope + ":" + provider, None)
            if connection and provider == "jira":
                job = self.runtime.connect_jobs.pop(connection["server"], None)
                if job:
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)
                check_write(self.runtime)
                path = self.runtime.config.settings.mcp_config_path
                if path and path.exists() and "mcp_config_path" not in self.runtime.config.locked_fields():
                    servers = json.loads(path.read_text()).get("servers", {})
                    servers.pop(connection["server"], None)
                    save_mcp_config(self.runtime.config, {"servers": servers})
                oauth = self.runtime.config.data_dir / "oauth" / connection["server"]
                if oauth.exists() and not oauth.is_symlink():
                    shutil.rmtree(oauth)
                self.runtime.mcp.statuses.pop(connection["server"], None)
            save_private(self.runtime.config, "development.json", values)
            return {"state": "disconnected"}


def install_development_routes(app, runtime):
    @app.get("/api/development")
    async def listing(scope: Scope = "work"):
        return runtime.development.listing(scope)

    @app.put("/api/development")
    async def save(data: DevelopmentConnection):
        return await runtime.development.save(data)

    @app.delete("/api/development/{provider}")
    async def disconnect(provider: Literal["jira", "github"], data: DevelopmentContext):
        owner_write(runtime, data.scope, data.privacy_revision)
        return await runtime.development.disconnect(data.scope, provider)

    @app.post("/api/development/{provider}/connect")
    async def connect(provider: Literal["jira", "github"], data: DevelopmentContext):
        owner_write(runtime, data.scope, data.privacy_revision)
        connection = next((x for x in runtime.development.listing(data.scope) if x["provider"] == provider), None)
        if not connection:
            raise ValueError("Configure the integration first.")
        if provider == "jira":
            return await runtime.connect(connection["server"])
        return await runtime.development.github_list(data.scope, connection["allowed"][0], runtime.config.settings.profile)

    @app.get("/api/development/summary")
    async def summary(scope: Scope = "work"):
        return await runtime.development.summary(scope, runtime.config.settings.profile)

    @app.get("/api/development/jira/issues")
    async def jira(scope: Scope = "work", project: str = "BVTL", query: str = "", cursor: str = ""):
        return await runtime.development.jira_search(scope, project, runtime.config.settings.profile, query, cursor=cursor)

    @app.get("/api/development/github/items")
    async def github(repository: str, scope: Scope = "work", kind: Literal["pulls", "issues"] = "pulls", page: int = 1):
        return await runtime.development.github_list(scope, repository, runtime.config.settings.profile, kind, page)

    @app.get("/api/development/github/pull/{number}")
    async def pull(number: int, repository: str, scope: Scope = "work"):
        return await runtime.development.github_pull(scope, repository, number, runtime.config.settings.profile)
