"""
Batch operations for managing profiles at scale.

Uses asyncio.Semaphore for concurrency control during browser-dependent
operations like warmup, health checks, and screenshot audits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import Profile

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a single batch operation on one profile."""

    profile_id: str
    profile_name: str
    success: bool
    error: Optional[str] = None
    details: Any = None


@dataclass
class BatchReport:
    """Aggregated report for a batch operation."""

    operation: str
    total: int
    succeeded: int = 0
    failed: int = 0
    results: List[BatchResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.succeeded / self.total * 100) if self.total > 0 else 0.0


async def batch_create(
    manager: Any,  # ProfileManager — avoid circular import
    prefix: str,
    count: int,
    os: str = "windows",
    tags: Optional[List[str]] = None,
    proxy_ids: Optional[List[str]] = None,
    **create_kwargs: Any,
) -> BatchReport:
    """
    Create multiple profiles with sequential naming.

    Args:
        manager: ProfileManager instance.
        prefix: Name prefix (e.g., "farm-" -> "farm-001", "farm-002").
        count: Number of profiles to create.
        os: Target OS for all profiles.
        tags: Tags applied to all profiles.
        proxy_ids: Optional list of proxy IDs to cycle through.
    """
    report = BatchReport(operation="create_batch", total=count)

    for i in range(1, count + 1):
        name = f"{prefix}{i:03d}"
        try:
            # Cycle through proxy_ids if provided
            proxy_kwargs = {}
            if proxy_ids:
                proxy_id = proxy_ids[(i - 1) % len(proxy_ids)]
                proxy_kwargs["proxy_id"] = proxy_id

            profile = await manager.create_profile(
                name=name,
                os=os,
                tags=tags,
                **proxy_kwargs,
                **create_kwargs,
            )
            report.results.append(BatchResult(
                profile_id=profile.id,
                profile_name=profile.name,
                success=True,
            ))
            report.succeeded += 1
            logger.info("Created profile %d/%d: %s", i, count, name)

        except Exception as e:
            report.results.append(BatchResult(
                profile_id="",
                profile_name=name,
                success=False,
                error=str(e),
            ))
            report.failed += 1
            logger.error("Failed to create profile %s: %s", name, e)

    return report


async def batch_warmup(
    manager: Any,
    profiles: List[Profile],
    concurrency: int = 5,
    max_sites: int = 10,
    headless: bool = True,
) -> BatchReport:
    """
    Warmup multiple profiles in parallel.

    Args:
        manager: ProfileManager instance.
        profiles: Profiles to warm up.
        concurrency: Max parallel browser instances.
        max_sites: Max sites per warmup session.
        headless: Run warmup headless.
    """
    report = BatchReport(operation="warmup_batch", total=len(profiles))
    semaphore = asyncio.Semaphore(concurrency)

    async def _warmup_one(profile: Profile) -> BatchResult:
        async with semaphore:
            try:
                warmup_report = await manager.warmup(
                    profile.id,
                    max_sites=max_sites,
                    headless=headless,
                )
                logger.info(
                    "Warmed up '%s': %d/%d sites",
                    profile.name,
                    warmup_report.sites_visited,
                    warmup_report.sites_attempted,
                )
                return BatchResult(
                    profile_id=profile.id,
                    profile_name=profile.name,
                    success=True,
                    details=warmup_report,
                )
            except Exception as e:
                logger.error("Warmup failed for '%s': %s", profile.name, e)
                return BatchResult(
                    profile_id=profile.id,
                    profile_name=profile.name,
                    success=False,
                    error=str(e),
                )

    results = await asyncio.gather(*[_warmup_one(p) for p in profiles])

    for r in results:
        report.results.append(r)
        if r.success:
            report.succeeded += 1
        else:
            report.failed += 1

    return report


async def batch_health_check(
    manager: Any,
    profiles: List[Profile],
    concurrency: int = 5,
) -> BatchReport:
    """
    Run health checks on multiple profiles in parallel.

    Args:
        manager: ProfileManager instance.
        profiles: Profiles to check.
        concurrency: Max parallel checks.
    """
    report = BatchReport(operation="health_check_batch", total=len(profiles))
    semaphore = asyncio.Semaphore(concurrency)

    async def _check_one(profile: Profile) -> BatchResult:
        async with semaphore:
            try:
                health = await manager.health_check(profile.id)
                return BatchResult(
                    profile_id=profile.id,
                    profile_name=profile.name,
                    success=health.status != "critical",
                    details=health,
                )
            except Exception as e:
                return BatchResult(
                    profile_id=profile.id,
                    profile_name=profile.name,
                    success=False,
                    error=str(e),
                )

    results = await asyncio.gather(*[_check_one(p) for p in profiles])

    for r in results:
        report.results.append(r)
        if r.success:
            report.succeeded += 1
        else:
            report.failed += 1

    return report
