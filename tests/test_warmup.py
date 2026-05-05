"""Tests for warmup engine."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from camoufox_profiles.warmup import DEFAULT_WARMUP_SITES, WarmupReport, warmup_profile


class MockPage:
    """Mock Playwright page for testing warmup."""

    def __init__(self, url: str = ""):
        self.url = url
        self._closed = False

    async def goto(self, url, **kwargs):
        self.url = url

    async def evaluate(self, script):
        if "scrollHeight" in script:
            return 2000
        if "innerHeight" in script:
            return 800
        if "scrollTo" in script:
            return None
        return None

    async def close(self):
        self._closed = True

    def locator(self, selector):
        mock = MagicMock()
        mock.first = mock
        mock.is_visible = AsyncMock(return_value=False)
        return mock


class MockContext:
    """Mock Playwright BrowserContext."""

    def __init__(self):
        self.pages: list = []
        self._new_page_count = 0

    async def new_page(self):
        page = MockPage()
        self.pages.append(page)
        self._new_page_count += 1
        return page


class TestWarmupProfile:
    """Tests for warmup_profile function."""

    async def test_warmup_visits_sites(self):
        """Test that warmup visits the specified number of sites."""
        context = MockContext()
        report = await warmup_profile(
            context=context,
            profile_id="test-id",
            max_sites=3,
            min_dwell_time=0.01,
            max_dwell_time=0.02,
        )

        assert report.profile_id == "test-id"
        assert report.total_visits == 3
        assert report.successful_visits == 3
        assert report.failed_visits == 0
        assert report.completed_at is not None

    async def test_warmup_with_extra_urls(self):
        """Test warmup includes extra URLs."""
        context = MockContext()
        extra = ["https://custom1.com", "https://custom2.com"]
        report = await warmup_profile(
            context=context,
            profile_id="test-id",
            extra_urls=extra,
            max_sites=20,  # High limit to include all
            min_dwell_time=0.01,
            max_dwell_time=0.02,
        )

        # Should visit defaults + extras
        assert report.total_visits == len(DEFAULT_WARMUP_SITES) + len(extra)

    async def test_warmup_max_sites_limit(self):
        """Test that max_sites limits the number of visits."""
        context = MockContext()
        report = await warmup_profile(
            context=context,
            profile_id="test-id",
            max_sites=5,
            min_dwell_time=0.01,
            max_dwell_time=0.02,
        )

        assert report.total_visits == 5

    async def test_warmup_report_structure(self):
        """Test WarmupReport dataclass fields."""
        report = WarmupReport(profile_id="test")
        assert report.total_visits == 0
        assert report.successful_visits == 0
        assert report.failed_visits == 0

    async def test_warmup_handles_page_errors(self):
        """Test that warmup continues when individual pages fail."""
        context = MockContext()

        # Patch new_page to fail on the second call
        original_new_page = context.new_page
        call_count = 0

        async def flaky_new_page():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Connection refused")
            return await original_new_page()

        context.new_page = flaky_new_page

        report = await warmup_profile(
            context=context,
            profile_id="test-id",
            max_sites=3,
            min_dwell_time=0.01,
            max_dwell_time=0.02,
        )

        # Should have 3 total visits (2 success + 1 failure)
        assert report.total_visits == 3
        assert report.successful_visits == 2
        assert report.failed_visits == 1


class TestDefaultWarmupSites:
    """Tests for DEFAULT_WARMUP_SITES list."""

    def test_default_sites_not_empty(self):
        assert len(DEFAULT_WARMUP_SITES) > 0

    def test_default_sites_are_https(self):
        for url in DEFAULT_WARMUP_SITES:
            assert url.startswith("https://"), f"Non-HTTPS URL: {url}"

    def test_default_sites_are_unique(self):
        assert len(DEFAULT_WARMUP_SITES) == len(set(DEFAULT_WARMUP_SITES))
