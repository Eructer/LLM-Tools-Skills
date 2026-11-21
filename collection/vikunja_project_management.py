"""
title: Vikunja Project Management
author: Eructer
version: 0.2.0
description: Manage projects in Vikunja
requirements: requests
"""

import json
import asyncio
import requests
from typing import Callable, Any, Optional
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default="http://localhost:8000/api/v2",
            description="Vikunja base url",
        )
        api_token: str = Field(default="", description="API token")
        timeout: int = Field(default=30, description="Request timeout in seconds")

    class UserValves(BaseModel):
        base_url: str = Field(
            default="",
            description="Override Vikunja base url (leave blank to use the admin default)",
        )
        api_token: str = Field(
            default="",
            description="API token (leave blank to use the admin default)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    # ---------- helpers (underscore = not exposed to the model) ----------

    def _config(self, __user__: dict):
        uv = (__user__ or {}).get("valves")
        base_url = (getattr(uv, "base_url", "") or self.valves.base_url).rstrip("/")
        token = getattr(uv, "api_token", "") or self.valves.api_token
        return base_url, token

    async def _status(self, emitter, msg: str, done: bool = False):
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": msg, "done": done}}
            )

    def _request_sync(self, method, base_url, endpoint, token, params=None, body=None):
        resp = requests.request(
            method,
            f"{base_url}/{endpoint.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=body,
            timeout=self.valves.timeout,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text
        return resp.ok, resp.status_code, payload

    async def _call(
        self, __user__, emitter, start, done, method, endpoint, params=None, body=None
    ) -> str:
        base_url, token = self._config(__user__)
        if not token:
            return "ERROR: no API token configured. Set one in the tool's Valves."

        await self._status(emitter, start)
        try:
            ok, code, payload = await asyncio.to_thread(
                self._request_sync, method, base_url, endpoint, token, params, body
            )
        except Exception as e:
            await self._status(emitter, "Request failed", done=True)
            return f"ERROR: {e}"

        await self._status(emitter, done if ok else f"Failed ({code})", done=True)
        if not ok:
            return f"ERROR {code}: {payload}"
        return payload if isinstance(payload, str) else json.dumps(payload)

    # ---------- tools ----------

    async def list_projects(
        self,
        page: int = 1,
        per_page: int = 50,
        query: str = "",
        is_archived: bool = False,
        doc_format: str = "markdown",
        __user__: dict = {},
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Get a list of projects.

        :param page: Page number. Defaults to 1.
        :param per_page: Items per page. Defaults to 50.
        :param query: Optional search text; filters the list to matching projects.
        :param is_archived: If true, also returns archived projects.
        :param doc_format: How rich-text fields are returned. Either `html` or `markdown`.
        :return: JSON list of projects.
        """
        params = {
            "page": page,
            "per_page": per_page,
            "is_archived": str(is_archived).lower(),
            "format": doc_format,
        }
        if query:
            params["query"] = query
        return await self._call(
            __user__, __event_emitter__,
            "Getting projects...", "Fetched projects",
            "GET", "projects", params=params,
        )

    async def get_project(
        self,
        id: int,
        __user__: dict = {},
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Get a project given its id.

        :param id: The project id.
        :return: JSON project.
        """
        return await self._call(
            __user__, __event_emitter__,
            f"Getting project {id}...", "Fetched project",
            "GET", f"projects/{id}",
        )

    async def create_project(
        self,
        title: str,
        description: str = "",
        hex_color: str = "",
        identifier: str = "",
        is_archived: bool = False,
        is_favorite: bool = False,
        parent_project_id: int = 0,
        position: int = 0,
        __user__: dict = {},
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Create a project.

        :param title: The title of the project.
        :param description: The description of the project.
        :param hex_color: Hex color without the leading `#`.
        :param identifier: Unique short identifier, used to build task identifiers (e.g. PROJ-123).
        :param is_archived: Whether the project is archived. Archived projects are read-only.
        :param is_favorite: Whether the project is a favorite of the requesting user.
        :param parent_project_id: Id of the parent project, or 0 for a top-level project.
        :param position: Position of this project when listing all projects.
        :return: JSON of the created project.
        """
        body = {
            "title": title,
            "description": description,
            "hex_color": hex_color,
            "identifier": identifier,
            "is_archived": is_archived,
            "is_favorite": is_favorite,
            "parent_project_id": parent_project_id,
            "position": position,
        }

        return await self._call(
            __user__, __event_emitter__,
            f"Creating project: {title}", "Created project",
            "POST", "projects", body=body,
        )

    async def update_project(
        self,
        id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        hex_color: Optional[str] = None,
        identifier: Optional[str] = None,
        is_archived: Optional[bool] = None,
        is_favorite: Optional[bool] = None,
        parent_project_id: Optional[int] = None,
        position: Optional[int] = None,
        __user__: dict = {},
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Update a project. Only the fields you provide are changed.

        :param id: The project id.
        :param title: New title.
        :param description: New description.
        :param hex_color: New hex color without the leading `#`.
        :param identifier: New unique short identifier.
        :param is_archived: Whether the project is archived.
        :param is_favorite: Whether the project is a favorite of the requesting user.
        :param parent_project_id: New parent project id, or 0 for top-level.
        :param position: New position when listing all projects.
        :return: JSON of the updated project.
        """
        base_url, token = self._config(__user__)
        if not token:
            return "ERROR: no API token configured. Set one in the tool's Valves."

        # Fetch current state so unspecified fields are preserved
        try:
            ok, code, current = await asyncio.to_thread(
                self._request_sync, "GET", base_url, f"projects/{id}", token
            )
        except Exception as e:
            return f"ERROR: {e}"
        if not ok or not isinstance(current, dict):
            return f"ERROR fetching project {id} ({code}): {current}"

        changes = {
            k: v
            for k, v in {
                "title": title,
                "description": description,
                "hex_color": hex_color,
                "identifier": identifier,
                "is_archived": is_archived,
                "is_favorite": is_favorite,
                "parent_project_id": parent_project_id,
                "position": position,
            }.items()
            if v is not None
        }
        if not changes:
            return "No changes provided."

        return await self._call(
            __user__, __event_emitter__,
            f"Updating project {id}...", "Updated project",
            "PUT", f"projects/{id}", body={**current, **changes},
        )

    async def delete_project(
        self,
        id: int,
        __user__: dict = {},
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
        __event_call__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Delete a project permanently. The user is asked to confirm first.

        :param id: The project id.
        :return: Result of the deletion.
        """
        if not __event_call__:
            return "Cannot confirm deletion without an interactive session. Nothing was deleted."

        confirmed = await __event_call__(
            {
                "type": "confirmation",
                "data": {
                    "title": "Delete project?",
                    "message": f"This permanently deletes project {id}.",
                },
            }
        )
        if not confirmed:
            return "User cancelled. Nothing was deleted."

        return await self._call(
            __user__, __event_emitter__,
            f"Deleting project {id}...", "Deleted project",
            "DELETE", f"projects/{id}",
        )