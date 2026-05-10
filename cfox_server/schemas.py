"""Pydantic v2 request/response schemas for cfox-server API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Profile schemas ────────────────────────────────────────────

class ProfileCreate(BaseModel):
    name: str
    target_os: str = "windows"
    fingerprint_config: Dict[str, Any]
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: str = ""
    proxy_id: Optional[str] = None
    user_data_dir: str = ""


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    total_sessions: Optional[int] = None
    last_used_at: Optional[str] = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: Optional[str] = None
    target_os: str
    fingerprint_config: Dict[str, Any]
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    user_data_dir: str
    total_sessions: int = 0
    tags: List[str] = Field(default_factory=list)
    notes: str = ""
    firefox_base_version: Optional[int] = None
    proxy_id: Optional[str] = None
    warmup_completed: bool = False
    # Cloud fields
    locked_by: Optional[str] = None
    lock_expires_at: Optional[str] = None
    essential_data_version: int = 0
    essential_data_size_bytes: int = 0
    sync_incomplete: bool = False
    last_synced_at: Optional[str] = None
    last_sync_machine: Optional[str] = None


class ProfileListResponse(BaseModel):
    profiles: List[ProfileResponse]
    total: int


# ── Lock schemas ───────────────────────────────────────────────

class LockRequest(BaseModel):
    machine_id: str
    ttl_minutes: int = 120


class LockResponse(BaseModel):
    lock_token: str
    locked_by: str
    locked_at: str
    lock_expires_at: str
    essential_data_version: int
    previous_lock: Optional[Dict[str, Any]] = None


class HeartbeatRequest(BaseModel):
    lock_token: str
    machine_id: str


class UnlockRequest(BaseModel):
    lock_token: str
    machine_id: str


# ── Essential data schemas ─────────────────────────────────────

class EssentialDataInfo(BaseModel):
    version: int
    size_bytes: int
    checksum: Optional[str] = None
    uploaded_at: Optional[str] = None


class VersionListItem(BaseModel):
    version: int
    size_bytes: int
    created_at: str


# ── User schemas ───────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    label: str = ""
    role: str = "member"


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    label: str
    created_at: str
    last_used_at: Optional[str] = None
    api_key: Optional[str] = None  # Only returned on create/rotate


class UserListResponse(BaseModel):
    users: List[UserResponse]


# ── Generic ────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
