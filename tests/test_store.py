"""Tests for ProfileStore and ProfileStoreSync."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from camoufox_profiles.exceptions import ProfileNameExistsError, ProfileNotFoundError
from camoufox_profiles.models import ProxyConfig
from camoufox_profiles.store import ProfileStore, ProfileStoreSync


# --- Fixtures ---


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test data."""
    return tmp_path / "test_profiles"


@pytest.fixture
async def async_store(tmp_dir):
    """Provide an initialized async ProfileStore."""
    store = ProfileStore(tmp_dir)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def sync_store(tmp_dir):
    """Provide an initialized sync ProfileStore."""
    store = ProfileStoreSync(tmp_dir)
    store.initialize()
    yield store
    store.close()


# --- Sample data ---

SAMPLE_FINGERPRINT = {
    "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "navigator.platform": "Win32",
    "navigator.hardwareConcurrency": 8,
    "screen.width": 1920,
    "screen.height": 1080,
    "webGl:renderer": "ANGLE (NVIDIA GeForce GTX 1060)",
    "webGl:vendor": "Google Inc. (NVIDIA)",
    "canvas:aaOffset": 15,
    "fonts:spacing_seed": 123456789,
}


# --- Async Store Tests ---


class TestProfileStoreAsync:
    """Tests for async ProfileStore."""

    async def test_create_profile(self, async_store):
        """Test creating a profile with fingerprint config."""
        profile = await async_store.create(
            name="test-1",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
            tags=["shop", "us"],
            notes="Test profile",
        )

        assert profile.name == "test-1"
        assert profile.target_os == "windows"
        assert profile.fingerprint_config == SAMPLE_FINGERPRINT
        assert profile.tags == ["shop", "us"]
        assert profile.total_sessions == 0
        assert profile.id  # UUID generated
        assert profile.user_data_dir  # Path generated
        assert Path(profile.user_data_dir).exists()

    async def test_create_with_proxy(self, async_store):
        """Test creating a profile with proxy binding."""
        proxy = ProxyConfig(
            server="http://proxy.example.com:8080",
            username="user",
            password="pass",
        )
        profile = await async_store.create(
            name="proxy-test",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
            proxy=proxy,
        )

        assert profile.proxy is not None
        assert profile.proxy.server == "http://proxy.example.com:8080"
        assert profile.proxy.username == "user"

    async def test_create_duplicate_name_raises(self, async_store):
        """Test that duplicate names raise an error."""
        await async_store.create(
            name="unique-name",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        with pytest.raises(ProfileNameExistsError):
            await async_store.create(
                name="unique-name",
                target_os="windows",
                fingerprint_config=SAMPLE_FINGERPRINT,
            )

    async def test_get_profile(self, async_store):
        """Test loading a profile by ID."""
        created = await async_store.create(
            name="get-test",
            target_os="macos",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        loaded = await async_store.get(created.id)
        assert loaded.id == created.id
        assert loaded.name == "get-test"
        assert loaded.target_os == "macos"
        assert loaded.fingerprint_config == SAMPLE_FINGERPRINT

    async def test_get_by_name(self, async_store):
        """Test loading a profile by name."""
        created = await async_store.create(
            name="name-lookup",
            target_os="linux",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        loaded = await async_store.get_by_name("name-lookup")
        assert loaded.id == created.id

    async def test_get_nonexistent_raises(self, async_store):
        """Test that missing profile raises an error."""
        with pytest.raises(ProfileNotFoundError):
            await async_store.get("nonexistent-id")

    async def test_list_profiles(self, async_store):
        """Test listing profiles with pagination."""
        for i in range(5):
            await async_store.create(
                name=f"list-{i}",
                target_os="windows",
                fingerprint_config=SAMPLE_FINGERPRINT,
            )

        all_profiles = await async_store.list(limit=100)
        assert len(all_profiles) == 5

        page1 = await async_store.list(limit=2)
        assert len(page1) == 2

        page2 = await async_store.list(limit=2, offset=2)
        assert len(page2) == 2

    async def test_list_filter_by_tag(self, async_store):
        """Test filtering profiles by tag."""
        await async_store.create(
            name="tagged-1",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
            tags=["shop", "us"],
        )
        await async_store.create(
            name="tagged-2",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
            tags=["social", "eu"],
        )

        shop_profiles = await async_store.list(tag="shop")
        assert len(shop_profiles) == 1
        assert shop_profiles[0].name == "tagged-1"

    async def test_list_filter_by_os(self, async_store):
        """Test filtering profiles by target OS."""
        await async_store.create(
            name="win-1",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )
        await async_store.create(
            name="mac-1",
            target_os="macos",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        win_profiles = await async_store.list(target_os="windows")
        assert len(win_profiles) == 1
        assert win_profiles[0].name == "win-1"

    async def test_update_profile(self, async_store):
        """Test updating mutable fields."""
        created = await async_store.create(
            name="update-test",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        updated = await async_store.update(
            created.id,
            name="updated-name",
            tags=["new-tag"],
            notes="Updated notes",
        )

        assert updated.name == "updated-name"
        assert updated.tags == ["new-tag"]
        assert updated.notes == "Updated notes"
        # Fingerprint should be unchanged
        assert updated.fingerprint_config == SAMPLE_FINGERPRINT

    async def test_record_session(self, async_store):
        """Test session counter increment."""
        created = await async_store.create(
            name="session-test",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )
        assert created.total_sessions == 0

        await async_store.record_session(created.id)
        await async_store.record_session(created.id)
        await async_store.record_session(created.id)

        loaded = await async_store.get(created.id)
        assert loaded.total_sessions == 3
        assert loaded.last_used_at is not None

    async def test_delete_profile(self, async_store):
        """Test deleting a profile and its browser data."""
        created = await async_store.create(
            name="delete-test",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )
        data_dir = Path(created.user_data_dir)
        assert data_dir.exists()

        await async_store.delete(created.id)

        with pytest.raises(ProfileNotFoundError):
            await async_store.get(created.id)

        assert not data_dir.exists()

    async def test_count(self, async_store):
        """Test counting profiles."""
        assert await async_store.count() == 0

        for i in range(3):
            await async_store.create(
                name=f"count-{i}",
                target_os="windows",
                fingerprint_config=SAMPLE_FINGERPRINT,
            )

        assert await async_store.count() == 3


# --- Sync Store Tests ---


class TestProfileStoreSync:
    """Tests for sync ProfileStoreSync."""

    def test_create_and_get(self, sync_store):
        """Test create and get round-trip."""
        profile = sync_store.create(
            name="sync-test",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
            tags=["test"],
        )

        loaded = sync_store.get(profile.id)
        assert loaded.name == "sync-test"
        assert loaded.fingerprint_config == SAMPLE_FINGERPRINT
        assert loaded.tags == ["test"]

    def test_list_and_count(self, sync_store):
        """Test listing and counting."""
        for i in range(3):
            sync_store.create(
                name=f"sync-list-{i}",
                target_os="windows",
                fingerprint_config=SAMPLE_FINGERPRINT,
            )

        assert sync_store.count() == 3
        profiles = sync_store.list()
        assert len(profiles) == 3

    def test_update_and_delete(self, sync_store):
        """Test update and delete."""
        profile = sync_store.create(
            name="sync-ud",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        updated = sync_store.update(profile.id, notes="hello")
        assert updated.notes == "hello"

        sync_store.delete(profile.id)
        with pytest.raises(ProfileNotFoundError):
            sync_store.get(profile.id)

    def test_duplicate_name_raises(self, sync_store):
        """Test duplicate name error."""
        sync_store.create(
            name="dup",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )
        with pytest.raises(ProfileNameExistsError):
            sync_store.create(
                name="dup",
                target_os="windows",
                fingerprint_config=SAMPLE_FINGERPRINT,
            )

    def test_record_session(self, sync_store):
        """Test session recording."""
        profile = sync_store.create(
            name="sync-session",
            target_os="windows",
            fingerprint_config=SAMPLE_FINGERPRINT,
        )

        sync_store.record_session(profile.id)
        sync_store.record_session(profile.id)

        loaded = sync_store.get(profile.id)
        assert loaded.total_sessions == 2
        assert loaded.last_used_at is not None
