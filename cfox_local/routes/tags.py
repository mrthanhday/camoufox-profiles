"""Tag management routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import orjson

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tags", tags=["tags"])


# ── Request models ───────────────────────────────────────────────


class CreateTagRequest(BaseModel):
    name: str
    color: str = ""


class UpdateTagRequest(BaseModel):
    new_name: Optional[str] = None
    color: Optional[str] = None


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager


def init_routes(profile_manager: Any, **_: Any) -> None:
    global _pm
    _pm = profile_manager


def _get_db() -> Any:
    """Get the shared database connection."""
    return _pm.store._ensure_db()


# ── Endpoints ────────────────────────────────────────────────────


@router.get("")
async def list_tags() -> Dict[str, Any]:
    """List all unique tags with usage counts and optional colors."""
    db = _get_db()

    # Get all profiles' tags
    async with db.execute("SELECT tags FROM profiles") as cursor:
        rows = await cursor.fetchall()

    # Aggregate unique tags with counts
    tag_counts: Dict[str, int] = {}
    for row in rows:
        tags_raw = row[0] if isinstance(row, tuple) else row["tags"]
        if tags_raw:
            try:
                tags = orjson.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except Exception:
                continue

    # Get colors from tags_meta
    colors: Dict[str, str] = {}
    try:
        async with db.execute("SELECT name, color FROM tags_meta") as cursor:
            meta_rows = await cursor.fetchall()
        for row in meta_rows:
            name = row[0] if isinstance(row, tuple) else row["name"]
            color = row[1] if isinstance(row, tuple) else row["color"]
            colors[name] = color or ""
    except Exception:
        pass  # Table may not exist yet on older DBs

    result = []
    # Include tags from both profiles and tags_meta
    all_tag_names = set(tag_counts.keys()) | set(colors.keys())
    for name in sorted(all_tag_names):
        result.append({
            "name": name,
            "color": colors.get(name, ""),
            "count": tag_counts.get(name, 0),
        })

    return {"tags": result}


@router.post("", status_code=201)
async def create_tag(req: CreateTagRequest) -> Dict[str, Any]:
    """Create a new tag (metadata only)."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")

    db = _get_db()
    name = req.name.strip().lower()

    # Check if tag already exists in meta
    async with db.execute("SELECT name FROM tags_meta WHERE name = ?", (name,)) as cursor:
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail=f"Tag '{name}' already exists")

    from camoufox_profiles.models import _utcnow
    await db.execute(
        "INSERT INTO tags_meta (name, color, created_at) VALUES (?, ?, ?)",
        (name, req.color or "", _utcnow().isoformat()),
    )
    await db.commit()

    return {"name": name, "color": req.color or "", "count": 0}


@router.put("/{tag_name}")
async def update_tag(tag_name: str, req: UpdateTagRequest) -> Dict[str, Any]:
    """Rename a tag and/or change its color. Renames propagate to all profiles."""
    db = _get_db()

    # Update color in tags_meta if provided
    if req.color is not None:
        from camoufox_profiles.models import _utcnow
        await db.execute(
            "INSERT OR REPLACE INTO tags_meta (name, color, created_at) VALUES (?, ?, ?)",
            (req.new_name or tag_name, req.color, _utcnow().isoformat()),
        )

    # Rename in all profiles if new_name provided
    if req.new_name and req.new_name != tag_name:
        new_name = req.new_name.strip().lower()

        # Find all profiles with the old tag (exact match via JSON deserialize)
        async with db.execute(
            "SELECT id, tags FROM profiles WHERE tags LIKE ?",
            (f'%"{tag_name}"%',)
        ) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            pid = row[0] if isinstance(row, tuple) else row["id"]
            tags_raw = row[1] if isinstance(row, tuple) else row["tags"]
            try:
                tags = orjson.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                # Exact match replacement + deduplicate
                new_tags = []
                seen = set()
                for t in tags:
                    replacement = new_name if t == tag_name else t
                    if replacement not in seen:
                        new_tags.append(replacement)
                        seen.add(replacement)
                await db.execute(
                    "UPDATE profiles SET tags = ? WHERE id = ?",
                    (orjson.dumps(new_tags).decode("utf-8"), pid),
                )
            except Exception:
                continue

        # Update tags_meta: delete old, ensure new exists
        await db.execute("DELETE FROM tags_meta WHERE name = ?", (tag_name,))

    await db.commit()

    final_name = req.new_name.strip().lower() if req.new_name else tag_name
    return {"name": final_name, "color": req.color if req.color is not None else ""}


@router.delete("/{tag_name}", status_code=204)
async def delete_tag(tag_name: str) -> None:
    """Remove a tag from all profiles and delete its metadata."""
    db = _get_db()

    # Remove from all profiles
    async with db.execute(
        "SELECT id, tags FROM profiles WHERE tags LIKE ?",
        (f'%"{tag_name}"%',)
    ) as cursor:
        rows = await cursor.fetchall()

    for row in rows:
        pid = row[0] if isinstance(row, tuple) else row["id"]
        tags_raw = row[1] if isinstance(row, tuple) else row["tags"]
        try:
            tags = orjson.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            # Exact match removal
            new_tags = [t for t in tags if t != tag_name]
            await db.execute(
                "UPDATE profiles SET tags = ? WHERE id = ?",
                (orjson.dumps(new_tags).decode("utf-8"), pid),
            )
        except Exception:
            continue

    # Delete from tags_meta
    await db.execute("DELETE FROM tags_meta WHERE name = ?", (tag_name,))
    await db.commit()
