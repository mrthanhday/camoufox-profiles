"""
Built-in warmup engine for antidetect browser profiles.

Visits popular websites to build natural browsing history before using
a profile for real tasks. This reduces the risk of detection from
"empty history" fingerprinting signals.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional

from .exceptions import WarmupError

logger = logging.getLogger(__name__)

# Default sites for warmup — popular, low-risk, diverse categories
DEFAULT_WARMUP_SITES = [
    "https://www.google.com",
    "https://www.youtube.com",
    "https://www.wikipedia.org",
    "https://www.amazon.com",
    "https://www.reddit.com",
    "https://github.com",
    "https://weather.com",
    "https://www.bbc.com",
    "https://stackoverflow.com",
    "https://www.linkedin.com",
    "https://www.nytimes.com",
    "https://www.twitch.tv",
    "https://www.imdb.com",
    "https://www.espn.com",
    "https://www.medium.com",
]


@dataclass
class WarmupVisit:
    """Record of a single warmup page visit."""

    url: str
    success: bool
    duration_seconds: float
    error: Optional[str] = None


@dataclass
class WarmupReport:
    """Summary report of a warmup session."""

    profile_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    visits: List[WarmupVisit] = field(default_factory=list)

    @property
    def total_visits(self) -> int:
        return len(self.visits)

    @property
    def successful_visits(self) -> int:
        return sum(1 for v in self.visits if v.success)

    @property
    def failed_visits(self) -> int:
        return sum(1 for v in self.visits if not v.success)

    @property
    def total_duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return sum(v.duration_seconds for v in self.visits)


async def warmup_profile(
    context: Any,
    profile_id: str = "",
    extra_urls: Optional[List[str]] = None,
    max_sites: int = 10,
    min_dwell_time: float = 3.0,
    max_dwell_time: float = 8.0,
    scroll: bool = True,
    close_tabs: bool = True,
) -> WarmupReport:
    """
    Visit popular sites to build natural browsing history.

    Simulates realistic browsing behavior:
    - Visits a random subset of default sites + any extra URLs
    - Spends a random dwell time on each page (human-like)
    - Scrolls down the page naturally
    - Accepts cookie banners when detected

    Args:
        context: Playwright BrowserContext (from launch_profile).
        profile_id: Profile ID for the report (optional).
        extra_urls: Additional URLs to visit alongside defaults.
        max_sites: Maximum number of sites to visit.
        min_dwell_time: Minimum seconds to spend on each page.
        max_dwell_time: Maximum seconds to spend on each page.
        scroll: Whether to scroll pages during warmup.
        close_tabs: Whether to close tabs after visiting (keeps last tab open).

    Returns:
        WarmupReport with visit details.

    Raises:
        WarmupError: If warmup fails critically.
    """
    report = WarmupReport(profile_id=profile_id)

    # Build URL list: defaults + extras, shuffled, limited
    all_urls = list(DEFAULT_WARMUP_SITES)
    if extra_urls:
        all_urls.extend(extra_urls)

    random.shuffle(all_urls)
    urls_to_visit = all_urls[:max_sites]

    logger.info(
        "Starting warmup for profile '%s': %d sites to visit",
        profile_id,
        len(urls_to_visit),
    )

    for i, url in enumerate(urls_to_visit):
        visit = await _visit_page(
            context=context,
            url=url,
            min_dwell=min_dwell_time,
            max_dwell=max_dwell_time,
            scroll=scroll,
        )
        report.visits.append(visit)

        if visit.success:
            logger.debug("Warmup [%d/%d] OK: %s (%.1fs)", i + 1, len(urls_to_visit), url, visit.duration_seconds)
        else:
            logger.debug("Warmup [%d/%d] FAIL: %s (%s)", i + 1, len(urls_to_visit), url, visit.error)

    # Close all tabs except the last one
    if close_tabs and len(context.pages) > 1:
        for page in context.pages[:-1]:
            try:
                await page.close()
            except Exception:
                pass

    report.completed_at = datetime.now(timezone.utc)

    logger.info(
        "Warmup complete for profile '%s': %d/%d sites visited successfully (%.0fs total)",
        profile_id,
        report.successful_visits,
        report.total_visits,
        report.total_duration_seconds,
    )

    return report


async def _visit_page(
    context: Any,
    url: str,
    min_dwell: float,
    max_dwell: float,
    scroll: bool,
) -> WarmupVisit:
    """Visit a single page with human-like behavior."""
    import time

    start = time.monotonic()

    try:
        page = await context.new_page()

        # Navigate with timeout
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        # Try to accept cookie banners (best-effort)
        await _try_accept_cookies(page)

        # Dwell time (random, human-like)
        dwell = random.uniform(min_dwell, max_dwell)

        # Scroll during dwell time
        if scroll:
            await _scroll_naturally(page, dwell)
        else:
            await asyncio.sleep(dwell)

        elapsed = time.monotonic() - start

        # Close the page
        try:
            await page.close()
        except Exception:
            pass

        return WarmupVisit(url=url, success=True, duration_seconds=elapsed)

    except Exception as e:
        elapsed = time.monotonic() - start
        return WarmupVisit(
            url=url,
            success=False,
            duration_seconds=elapsed,
            error=str(e)[:200],
        )


async def _scroll_naturally(page: Any, total_time: float) -> None:
    """Scroll the page in a natural, human-like manner."""
    try:
        # Get page height
        page_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = await page.evaluate("window.innerHeight")

        if page_height <= viewport_height:
            # Page fits in viewport, just wait
            await asyncio.sleep(total_time)
            return

        # Calculate scroll target (30-70% of page)
        scroll_target = random.uniform(0.3, 0.7) * page_height

        # Break scroll into smaller steps
        num_steps = random.randint(3, 7)
        step_size = scroll_target / num_steps
        step_delay = total_time / (num_steps + 1)  # +1 for initial pause

        # Initial reading pause
        await asyncio.sleep(step_delay * random.uniform(0.5, 1.5))

        current_scroll = 0
        for _ in range(num_steps):
            # Add some randomness to each step
            actual_step = step_size * random.uniform(0.7, 1.3)
            current_scroll += actual_step

            await page.evaluate(f"window.scrollTo(0, {int(current_scroll)})")
            await asyncio.sleep(step_delay * random.uniform(0.6, 1.4))

    except Exception:
        # If scrolling fails, just wait out the remaining time
        await asyncio.sleep(max(0.5, total_time * 0.3))


async def _try_accept_cookies(page: Any) -> None:
    """Try to click common cookie consent buttons (best-effort, non-blocking)."""
    # Common cookie banner selectors
    selectors = [
        # Common button text patterns
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        'button:has-text("Agree")',
        # Common IDs/classes
        "#onetrust-accept-btn-handler",
        "#accept-cookies",
        ".cookie-accept",
        '[data-testid="cookie-policy-manage-dialog-btn-accept"]',
    ]

    for selector in selectors:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=500):
                await button.click(timeout=1000)
                return
        except Exception:
            continue
