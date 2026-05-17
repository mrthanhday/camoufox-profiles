"""
Cloud client for cfox-local to communicate with cfox-server.

Handles authentication, retries, connection management, and caching.
All cloud operations go through this client.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Cache TTL for profile list (seconds)
CACHE_TTL = 30


class CloudClient:
    """
    HTTP client for cfox-server API.

    Features:
    - API key authentication via X-API-Key header
    - Automatic retries with exponential backoff
    - Profile list caching (30s TTL)
    - Connection health check
    """

    def __init__(
        self,
        server_url: str,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.server_url = server_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

        # Profile list cache
        self._profile_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: float = 0

    async def connect(self) -> bool:
        """Initialize the HTTP client and check server health."""
        self._client = httpx.AsyncClient(
            base_url=self.server_url,
            headers={"X-API-Key": self._api_key},
            timeout=self._timeout,
        )
        return await self.health_check()

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._invalidate_cache()

    async def health_check(self) -> bool:
        """Check if cfox-server is reachable."""
        try:
            resp = await self._request("GET", "/api/health")
            return resp.get("status") == "ok"
        except Exception as e:
            logger.warning("Server health check failed: %s", e)
            return False

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    # ── Profile operations ─────────────────────────────────────────

    async def list_profiles(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """List cloud profiles with caching."""
        # Check cache (only for unfiltered requests)
        if use_cache and not any([tag, target_os, search, offset]):
            if self._profile_cache and (time.monotonic() - self._cache_time) < CACHE_TTL:
                return {"profiles": self._profile_cache, "total": len(self._profile_cache)}

        params = {"limit": limit, "offset": offset}
        if tag:
            params["tag"] = tag
        if target_os:
            params["target_os"] = target_os
        if search:
            params["search"] = search

        result = await self._request("GET", "/api/profiles", params=params)

        # Update cache for unfiltered requests
        if not any([tag, target_os, search, offset]):
            self._profile_cache = result.get("profiles", [])
            self._cache_time = time.monotonic()

        return result

    async def get_profile(self, profile_id: str) -> Dict[str, Any]:
        """Get a single cloud profile."""
        return await self._request("GET", f"/api/profiles/{profile_id}")

    async def create_profile(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a cloud profile."""
        result = await self._request("POST", "/api/profiles", json=data)
        self._invalidate_cache()
        return result

    async def update_profile(
        self,
        profile_id: str,
        data: Dict[str, Any],
        if_match: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Update a cloud profile with optional optimistic concurrency."""
        headers = {}
        if if_match is not None:
            headers["If-Match"] = str(if_match)
        result = await self._request(
            "PATCH", f"/api/profiles/{profile_id}", json=data, headers=headers,
        )
        self._invalidate_cache()
        return result

    async def delete_profile(self, profile_id: str) -> Dict[str, Any]:
        """Delete a cloud profile."""
        result = await self._request("DELETE", f"/api/profiles/{profile_id}")
        self._invalidate_cache()
        return result

    # ── Lock operations ────────────────────────────────────────────

    async def lock_profile(
        self, profile_id: str, machine_id: str, ttl_minutes: int = 120,
    ) -> Dict[str, Any]:
        """Acquire lock on a cloud profile."""
        return await self._request(
            "POST", f"/api/profiles/{profile_id}/lock",
            json={"machine_id": machine_id, "ttl_minutes": ttl_minutes},
        )

    async def heartbeat(
        self, profile_id: str, lock_token: str, machine_id: str,
    ) -> Dict[str, Any]:
        """Send heartbeat to renew lock TTL."""
        return await self._request(
            "POST", f"/api/profiles/{profile_id}/heartbeat",
            json={"lock_token": lock_token, "machine_id": machine_id},
        )

    async def unlock_profile(
        self, profile_id: str, lock_token: str, machine_id: str,
    ) -> Dict[str, Any]:
        """Release lock on a cloud profile."""
        return await self._request(
            "POST", f"/api/profiles/{profile_id}/unlock",
            json={"lock_token": lock_token, "machine_id": machine_id},
        )

    # ── Essential data operations ──────────────────────────────────

    async def upload_essential_data(
        self, profile_id: str, zip_path: Path,
    ) -> Dict[str, Any]:
        """Upload essential data ZIP to server."""
        if not self._client:
            raise RuntimeError("Not connected")

        with open(zip_path, "rb") as f:
            resp = await self._client.post(
                f"/api/profiles/{profile_id}/essential-data",
                files={"file": ("essential.zip", f, "application/zip")},
            )

        if resp.status_code >= 400:
            raise CloudAPIError(resp.status_code, resp.text)
        return resp.json()

    async def download_essential_data(
        self, profile_id: str, output_path: Path, version: int = 0,
    ) -> Dict[str, str]:
        """Download essential data ZIP from server."""
        if not self._client:
            raise RuntimeError("Not connected")

        params = {"version": version} if version else {}
        resp = await self._client.get(
            f"/api/profiles/{profile_id}/essential-data",
            params=params,
        )

        if resp.status_code >= 400:
            raise CloudAPIError(resp.status_code, resp.text)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)

        return {
            "checksum": resp.headers.get("x-checksum", ""),
            "version": resp.headers.get("x-version", "0"),
        }

    # ── Internal ───────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request with retries (exponential backoff with jitter)."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        import asyncio
        import random

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.request(
                    method, path, json=json, params=params, headers=headers or {},
                )
                if resp.status_code >= 400:
                    raise CloudAPIError(resp.status_code, resp.text)
                return resp.json()

            except CloudAPIError:
                raise  # Don't retry API errors

            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_error = e
                if attempt + 1 >= self._max_retries:
                    break
                # Exponential backoff with full jitter to avoid thundering herd
                backoff = min(2 ** attempt, 32)
                wait = random.uniform(0, backoff)
                logger.warning(
                    "Request failed (attempt %d/%d), retry in %.1fs: %s",
                    attempt + 1, self._max_retries, wait, e,
                )
                await asyncio.sleep(wait)

        raise CloudConnectionError(f"Failed after {self._max_retries} attempts: {last_error}")

    def _invalidate_cache(self) -> None:
        """Clear the profile list cache."""
        self._profile_cache = None
        self._cache_time = 0


class CloudAPIError(Exception):
    """Error from cfox-server API."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class CloudConnectionError(Exception):
    """Connection failure to cfox-server."""
    pass
