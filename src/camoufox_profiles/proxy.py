"""
Centralized proxy pool management.

Manages proxies as shared resources in a database table. Profiles reference
proxies by ID. Supports health checking, manual rotation, and opt-in
auto-rotation from user-provided pools.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiosqlite
import orjson

from .models import ProxyPoolEntry, _new_id, _utcnow

logger = logging.getLogger(__name__)


async def check_proxy_health(
    server: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 10.0,
) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Check if a proxy is reachable and resolve its external IP.

    Returns:
        Tuple of (is_alive, external_ip, latency_ms).
    """
    parsed = urlparse(server)
    host = parsed.hostname or server
    port = parsed.port or 8080

    start = time.monotonic()
    try:
        # TCP connection test
        loop = asyncio.get_event_loop()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        latency = int((time.monotonic() - start) * 1000)

        # Try to resolve external IP through proxy
        external_ip = None
        try:
            from camoufox.ip import public_ip, Proxy
            proxy_str = server
            if username and password:
                proxy_str = f"{parsed.scheme}://{username}:{password}@{host}:{port}"
            external_ip = public_ip(proxy_str)
        except Exception:
            pass  # IP resolution is best-effort

        return True, external_ip, latency

    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        latency = int((time.monotonic() - start) * 1000)
        logger.debug("Proxy %s:%d unreachable: %s", host, port, e)
        return False, None, latency


class ProxyStore:
    """Async proxy pool storage operations."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def add(
        self,
        server: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: str = "",
    ) -> ProxyPoolEntry:
        """Add a proxy to the pool."""
        entry = ProxyPoolEntry(
            id=_new_id(),
            server=server,
            username=username,
            password=password,
            tags=tags or [],
            created_at=_utcnow().isoformat(),
            notes=notes,
        )

        await self._db.execute(
            """INSERT INTO proxy_pool (
                id, server, username, password, tags, is_alive,
                last_checked_at, last_ip, last_latency_ms,
                consecutive_failures, created_at, notes,
                auto_rotate_enabled, rotate_pool_tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id, entry.server, entry.username, entry.password,
                orjson.dumps(entry.tags).decode("utf-8"),
                1, None, None, None, 0,
                entry.created_at, entry.notes, 0, None,
            ),
        )
        await self._db.commit()
        return entry

    async def get(self, proxy_id: str) -> Optional[ProxyPoolEntry]:
        """Get a proxy by ID."""
        async with self._db.execute(
            "SELECT * FROM proxy_pool WHERE id = ?", (proxy_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None
        return self._row_to_entry(dict(row))

    async def list(
        self,
        tag: Optional[str] = None,
        alive_only: bool = False,
    ) -> List[ProxyPoolEntry]:
        """List proxies with optional filters."""
        conditions = []
        params: list = []

        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        if alive_only:
            conditions.append("is_alive = 1")

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM proxy_pool{where} ORDER BY created_at DESC"

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_entry(dict(r)) for r in rows]

    async def delete(self, proxy_id: str) -> None:
        """Remove a proxy from the pool."""
        await self._db.execute("DELETE FROM proxy_pool WHERE id = ?", (proxy_id,))
        await self._db.commit()

    async def update_health(
        self,
        proxy_id: str,
        is_alive: bool,
        external_ip: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        """Update proxy health status after a check."""
        now = _utcnow().isoformat()

        if is_alive:
            await self._db.execute(
                """UPDATE proxy_pool SET
                    is_alive = 1, last_checked_at = ?, last_ip = ?,
                    last_latency_ms = ?, consecutive_failures = 0
                WHERE id = ?""",
                (now, external_ip, latency_ms, proxy_id),
            )
        else:
            await self._db.execute(
                """UPDATE proxy_pool SET
                    is_alive = 0, last_checked_at = ?,
                    last_latency_ms = ?,
                    consecutive_failures = consecutive_failures + 1
                WHERE id = ?""",
                (now, latency_ms, proxy_id),
            )

        await self._db.commit()

    async def get_next_alive(self, pool_tag: str, exclude_id: Optional[str] = None) -> Optional[ProxyPoolEntry]:
        """Get the next alive proxy from a pool tag, excluding a specific proxy."""
        conditions = ["is_alive = 1", "tags LIKE ?"]
        params: list = [f'%"{pool_tag}"%']

        if exclude_id:
            conditions.append("id != ?")
            params.append(exclude_id)

        query = f"SELECT * FROM proxy_pool WHERE {' AND '.join(conditions)} ORDER BY last_checked_at ASC LIMIT 1"
        async with self._db.execute(query, params) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None
        return self._row_to_entry(dict(row))

    async def check_all(self, concurrency: int = 5) -> List[ProxyPoolEntry]:
        """Check all proxies health with concurrency control.

        Returns the full updated proxy list after all checks complete.
        """
        proxies = await self.list()
        semaphore = asyncio.Semaphore(concurrency)

        async def _check_one(entry: ProxyPoolEntry) -> None:
            async with semaphore:
                alive, ip, latency = await check_proxy_health(
                    entry.server, entry.username, entry.password
                )
                await self.update_health(entry.id, alive, ip, latency)

        tasks = [_check_one(p) for p in proxies]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Re-fetch to get updated health data
        return await self.list()

    @staticmethod
    def _row_to_entry(row: Dict[str, Any]) -> ProxyPoolEntry:
        """Convert a database row to a ProxyPoolEntry."""
        tags_raw = row.get("tags", "[]")
        if isinstance(tags_raw, str):
            tags = orjson.loads(tags_raw)
        else:
            tags = tags_raw or []

        return ProxyPoolEntry(
            id=row["id"],
            server=row["server"],
            username=row.get("username"),
            password=row.get("password"),
            tags=tags,
            is_alive=bool(row.get("is_alive", 1)),
            last_checked_at=row.get("last_checked_at"),
            last_ip=row.get("last_ip"),
            last_latency_ms=row.get("last_latency_ms"),
            consecutive_failures=row.get("consecutive_failures", 0),
            created_at=row.get("created_at", ""),
            notes=row.get("notes", ""),
            auto_rotate_enabled=bool(row.get("auto_rotate_enabled", 0)),
            rotate_pool_tag=row.get("rotate_pool_tag"),
        )
