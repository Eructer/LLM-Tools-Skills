"""
title: Deep Research Tool
author: Eructer
version: 0.1.1
description: Multi-round web research with cached urls and findings
requirements: requests
"""

import asyncio
import requests
from typing import Callable, Any, Optional, List, Dict
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default="http://localhost:8000",
            description="Search engine base url",
        )
        rounds: int = Field(default=5, description="Max number of search rounds")
        timeout: int = Field(default=30, description="Request timeout in seconds")
        max_results: int = Field(default=8, description="Results returned per search")

    class UserValves(BaseModel):
        base_url: str = Field(
            default="",
            description="Override search base url (leave blank to use the admin default)",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False  # we return our own structured data
        # chat_id -> {"urls": [], "findings": [], "searches": 0}
        self.sessions: Dict[str, dict] = {}

    # ---------- helpers (underscore = not exposed to the model) ----------

    def _session(self, __metadata__: dict, __messages__: Optional[list] = None) -> dict:
        md = __metadata__ or {}
        chat_id = md.get("chat_id", "default")

        turn = md.get("message_id")

        if not turn:
            user_count = sum(1 for m in (__messages or []) if m.get("role") == "user")
            turn = f"u{user_count}"

        key = f"{chat_id}:{turn}"

        if key not in self.sessions:
            self.sessions[key] = {"urls": [], "findings": [], "searches": 0}
            # Prune oldest sessions so memory keeps down
            while len(self.sessions) > 100:
                self.session.pop(next(iter(self.sessions)))
        return self.sessions[key]

    async def _status(self, emitter, msg: str, done: bool = False):
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": msg, "done": done}}
            )

    def _search_sync(self, base_url: str, query: str, categories: str) -> list:
        resp = requests.get(
            f"{base_url}/search",
            params={"q": query, "format": "json", "categories": categories},
            timeout=self.valves.timeout,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # Trim to what the model needs; raw payloads can be huge
        return [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
            }
            for r in results[: self.valves.max_results]
        ]

    # ---------- tools ----------

    async def web_search(
        self,
        query: str,
        categories: str = "general",
        __user__: dict = {},
        __metadata__: dict = {},
        __messages__: Optional[list] = None,
        __event_emitter__: Optional[Callable[[dict], Any]] = None,
    ) -> str:
        """
        Search the web. Use multiple searches with refined queries to research a topic.

        :param query: The search query. Example: "Why is the sky blue?"
        :param categories: One of 'general', 'news', 'images', 'videos', 'science', 'it', 'files', 'music', 'social media'. Defaults to 'general'.
        :return: Search results with title, url, and content snippet.
        """
        session = self._session(__metadata__, __messages__)

        if session["searches"] >= self.valves.rounds:
            return (
                f"Search limit of {self.valves.rounds} rounds reached. "
                "Do not search again. Call report() and write the final answer."
            )
        session["searches"] += 1

        user_valves = (__user__ or {}).get("valves")
        base_url = (
            getattr(user_valves, "base_url", "") or self.valves.base_url
        ).rstrip("/")

        await self._status(
            __event_emitter__,
            f"Searching ({session['searches']}/{self.valves.rounds}): {query}",
        )

        try:
            results = await asyncio.to_thread(
                self._search_sync, base_url, query, categories
            )
            output = str(results)
        except Exception as e:
            output = f"ERROR searching for '{query}': {e}"

        await self._status(__event_emitter__, "Search done", done=True)

        remaining = self.valves.rounds - session["searches"]
        return (
            f"{output}\n\n"
            f"Rounds remaining: {remaining}. Use cache_urls and cache_findings to save "
            "anything useful. Search again with a refined query if gaps remain, "
            "otherwise call report()."
        )

    def cache_urls(self, urls: List[str], __messages__: Optional[list] = None, __metadata__: dict = {}) -> str:
        """
        Save urls to cite in the final report.

        :param urls: List of urls to cache. Example: ["https://example.com/a", "https://example.com/b"]
        :return: Confirmation with the number of cached urls.
        """
        session = self._session(__metadata__, __messages__)
        for url in urls:
            if url not in session["urls"]:
                session["urls"].append(url)
        return f"Cached. Total urls: {len(session['urls'])}"

    def cache_findings(
        self, findings: List[Dict[str, str]], __messages__: Optional[list] = None, __metadata__: dict = {}
    ) -> str:
        """
        Save findings to use in the final report.

        :param findings: List of mappings with keys 'url' and 'finding'. Example: [{"url": "https://example.com", "finding": "Key fact here"}]
        :return: Confirmation with the number of cached findings.
        """
        session = self._session(__metadata__, __messages__)
        session["findings"].extend(findings)
        return f"Cached. Total findings: {len(session['findings'])}"

    def report(self, __messages__: Optional[list] = None, __metadata__: dict = {}) -> dict:
        """
        Retrieve all cached urls and findings. Call this when research is complete, then write the final answer using them.

        :return: Dict with 'findings' and 'urls'.
        """
        session = self._session(__metadata__, __messages__)
        return {
            "findings": session["findings"],
            "urls": session["urls"],
            "instructions": "Write a structured report using only these findings and cite the urls.",
        }