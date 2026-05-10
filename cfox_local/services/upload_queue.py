"""
Upload queue for essential data sync.

Manages background uploads with deduplication, concurrency control,
and exponential backoff retry.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class UploadJob:
    """A pending essential data upload."""
    profile_id: str
    zip_path: Path
    attempt: int = 0
    max_retries: int = 5


class UploadQueue:
    """
    Background upload queue with dedup and concurrency control.

    Features:
    - Dedup by profile_id (latest wins)
    - Max 3 concurrent uploads
    - Exponential backoff on failure (2^attempt seconds, max 32s)
    - Max 5 retries per job
    """

    def __init__(
        self,
        upload_fn: Callable,
        max_concurrent: int = 3,
        on_complete: Optional[Callable] = None,
        on_failure: Optional[Callable] = None,
    ):
        self._upload_fn = upload_fn  # async fn(profile_id, zip_path) -> dict
        self._max_concurrent = max_concurrent
        self._on_complete = on_complete
        self._on_failure = on_failure
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._pending: Dict[str, UploadJob] = {}
        self._active: Dict[str, asyncio.Task] = {}
        self._running = False

    def enqueue(self, profile_id: str, zip_path: Path) -> None:
        """
        Add an upload job. If a job for this profile_id already exists,
        it's replaced (dedup: latest wins).
        """
        job = UploadJob(profile_id=profile_id, zip_path=zip_path)

        if profile_id in self._active:
            # Already uploading — queue for re-upload after current finishes
            self._pending[profile_id] = job
            logger.debug("Upload re-queued (in-flight): %s", profile_id[:8])
        elif profile_id in self._pending:
            # Replace pending job with newer data
            self._pending[profile_id] = job
            logger.debug("Upload deduped: %s", profile_id[:8])
        else:
            self._pending[profile_id] = job
            asyncio.create_task(self._process_job(job))

    async def _process_job(self, job: UploadJob) -> None:
        """Process a single upload job with retry."""
        profile_id = job.profile_id

        async with self._semaphore:
            self._active[profile_id] = asyncio.current_task()
            self._pending.pop(profile_id, None)

            try:
                while job.attempt < job.max_retries:
                    try:
                        result = await self._upload_fn(profile_id, job.zip_path)
                        logger.info(
                            "Upload complete: profile=%s attempt=%d",
                            profile_id[:8], job.attempt + 1,
                        )
                        if self._on_complete:
                            await self._on_complete(profile_id, result)
                        break

                    except Exception as e:
                        job.attempt += 1
                        if job.attempt >= job.max_retries:
                            logger.error(
                                "Upload failed permanently: profile=%s error=%s",
                                profile_id[:8], e,
                            )
                            if self._on_failure:
                                await self._on_failure(profile_id, e)
                            break

                        wait = min(2 ** job.attempt, 32)
                        logger.warning(
                            "Upload failed (attempt %d/%d), retry in %ds: %s",
                            job.attempt, job.max_retries, wait, e,
                        )
                        await asyncio.sleep(wait)

            finally:
                self._active.pop(profile_id, None)

                # Process any re-queued job
                if profile_id in self._pending:
                    next_job = self._pending[profile_id]
                    asyncio.create_task(self._process_job(next_job))

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def active_count(self) -> int:
        return len(self._active)

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for all active uploads to complete."""
        tasks = list(self._active.values())
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
