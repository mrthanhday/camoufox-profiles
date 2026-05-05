"""Tests for fingerprint capture and replay."""

import pytest

from camoufox_profiles.fingerprint import extract_config_from_env


class TestExtractConfigFromEnv:
    """Test CAMOU_CONFIG extraction from environment variables."""

    def test_single_chunk(self):
        """Test extracting config from a single env var chunk."""
        env = {
            "CAMOU_CONFIG_1": '{"navigator.userAgent":"Mozilla/5.0","screen.width":1920}',
        }
        config = extract_config_from_env(env)
        assert config["navigator.userAgent"] == "Mozilla/5.0"
        assert config["screen.width"] == 1920

    def test_multiple_chunks(self):
        """Test extracting config from multiple ordered chunks."""
        env = {
            "CAMOU_CONFIG_1": '{"navigator.userAge',
            "CAMOU_CONFIG_2": 'nt":"Mozilla/5.0"}',
        }
        config = extract_config_from_env(env)
        assert config["navigator.userAgent"] == "Mozilla/5.0"

    def test_unordered_chunks(self):
        """Test that chunks are sorted by index regardless of dict order."""
        env = {
            "CAMOU_CONFIG_3": '0}',
            "CAMOU_CONFIG_1": '{"screen.width":192',
            "CAMOU_CONFIG_2": '',
        }
        config = extract_config_from_env(env)
        assert config["screen.width"] == 1920

    def test_empty_env(self):
        """Test with no CAMOU_CONFIG vars."""
        config = extract_config_from_env({"PATH": "/usr/bin", "HOME": "/home/user"})
        assert config == {}

    def test_non_config_vars_ignored(self):
        """Test that non-CAMOU_CONFIG vars are ignored."""
        env = {
            "PATH": "/usr/bin",
            "CAMOU_CONFIG_1": '{"test":true}',
            "OTHER_VAR": "value",
        }
        config = extract_config_from_env(env)
        assert config == {"test": True}

    def test_invalid_json_returns_empty(self):
        """Test that invalid JSON returns empty dict."""
        env = {
            "CAMOU_CONFIG_1": "not valid json",
        }
        config = extract_config_from_env(env)
        assert config == {}

    def test_complex_config(self):
        """Test with a realistic multi-key config."""
        import orjson

        full_config = {
            "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "navigator.platform": "Win32",
            "navigator.hardwareConcurrency": 8,
            "screen.width": 1920,
            "screen.height": 1080,
            "screen.colorDepth": 24,
            "webGl:renderer": "ANGLE (NVIDIA GeForce GTX 1060)",
            "webGl:vendor": "Google Inc. (NVIDIA)",
            "canvas:aaOffset": 15,
            "fonts:spacing_seed": 123456789,
            "timezone": "America/New_York",
            "locale:language": "en",
            "locale:region": "US",
        }

        # Simulate chunking (Camoufox splits at ~8000 chars)
        json_str = orjson.dumps(full_config).decode("utf-8")
        chunk_size = 50
        chunks = [json_str[i : i + chunk_size] for i in range(0, len(json_str), chunk_size)]

        env = {f"CAMOU_CONFIG_{i + 1}": chunk for i, chunk in enumerate(chunks)}

        result = extract_config_from_env(env)
        assert result == full_config
