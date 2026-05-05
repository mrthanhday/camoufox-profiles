"""
Fingerprint capture and replay for consistent profile identity.

This module intercepts Camoufox's fingerprint generation output and provides
methods to save and replay fingerprint configs across browser sessions.

Key insight: Camoufox's launch_options() uses merge_into() which only sets
keys that don't already exist in config. By passing a complete saved config,
all random generation is bypassed and the saved fingerprint is replayed exactly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import orjson

from .exceptions import FingerprintCaptureError

logger = logging.getLogger(__name__)


def capture_fingerprint(
    target_os: str = "windows",
    proxy: Optional[Dict[str, str]] = None,
    geoip: Optional[Union[str, bool]] = None,
    window: Optional[Tuple[int, int]] = None,
    block_webrtc: bool = False,
    fonts: Optional[List[str]] = None,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    Generate a Camoufox fingerprint config ONCE and return it for persistent storage.

    Calls Camoufox's launch_options() internally, extracts the finalized config
    dict from the environment variables, and returns it. This config can be
    saved to disk and replayed on every subsequent browser launch.

    Args:
        target_os: Target OS for fingerprint ('windows', 'macos', 'linux').
        proxy: Playwright proxy dict (server, username, password).
        geoip: IP address for geo lookup, True for auto-detect, or None.
        window: Fixed window size as (width, height) tuple.
        block_webrtc: Whether to block WebRTC entirely.
        fonts: Additional fonts to include.
        headless: Whether the browser will run headless (affects screen constraints).

    Returns:
        Complete Camoufox config dict containing all fingerprint properties.

    Raises:
        FingerprintCaptureError: If fingerprint generation fails.
    """
    try:
        from camoufox.utils import launch_options
    except ImportError as e:
        raise FingerprintCaptureError(
            "camoufox package is required. Install with: pip install camoufox[geoip]"
        ) from e

    try:
        opts = launch_options(
            os=target_os,
            proxy=proxy,
            geoip=geoip,
            window=window,
            block_webrtc=block_webrtc,
            fonts=fonts,
            headless=headless,
            i_know_what_im_doing=True,
        )
    except Exception as e:
        raise FingerprintCaptureError(str(e)) from e

    # Extract config from CAMOU_CONFIG_* env vars
    config = extract_config_from_env(opts.get("env", {}))
    if not config:
        raise FingerprintCaptureError(
            "No CAMOU_CONFIG found in launch options. "
            "Camoufox may have changed its config passing mechanism."
        )

    logger.info(
        "Captured fingerprint: OS=%s, UA=%s, keys=%d",
        target_os,
        config.get("navigator.userAgent", "unknown")[:60],
        len(config),
    )

    return config


def extract_config_from_env(env: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and reconstruct the Camoufox config from CAMOU_CONFIG_* env vars.

    Camoufox splits the config JSON into chunks stored in environment variables
    named CAMOU_CONFIG_1, CAMOU_CONFIG_2, etc. This function reassembles them.

    Args:
        env: Environment variables dict from launch_options() output.

    Returns:
        Reconstructed config dict.
    """
    # Collect all CAMOU_CONFIG chunks in order
    chunks: list[tuple[int, str]] = []
    for key, value in env.items():
        if isinstance(key, str) and key.startswith("CAMOU_CONFIG_"):
            try:
                idx = int(key.replace("CAMOU_CONFIG_", ""))
                chunks.append((idx, str(value)))
            except (ValueError, TypeError):
                continue

    if not chunks:
        return {}

    # Sort by index and concatenate
    chunks.sort(key=lambda x: x[0])
    config_json = "".join(chunk for _, chunk in chunks)

    try:
        return orjson.loads(config_json)
    except (orjson.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse CAMOU_CONFIG: %s", e)
        return {}


def build_launch_options(
    fingerprint_config: Dict[str, Any],
    proxy: Optional[Dict[str, str]] = None,
    user_data_dir: Optional[str] = None,
    headless: bool = False,
    humanize: Optional[Union[bool, float]] = None,
    addons: Optional[List[str]] = None,
    enable_cache: bool = False,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    extra_args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build Camoufox launch options from a saved fingerprint config.

    Passes the stored config to launch_options(config=...) so that
    merge_into() skips random generation for all pre-set keys.

    Args:
        fingerprint_config: Previously saved config dict from capture_fingerprint().
        proxy: Playwright proxy dict.
        user_data_dir: Path for persistent browser data (enables persistent context).
        headless: Run headless.
        humanize: Enable human-like cursor movement.
        addons: List of addon paths.
        enable_cache: Cache pages and requests.
        firefox_user_prefs: Firefox user preferences.
        extra_args: Extra browser launch args.

    Returns:
        Complete launch options dict ready for Playwright.
    """
    try:
        from camoufox.utils import launch_options
    except ImportError as e:
        raise FingerprintCaptureError(
            "camoufox package is required. Install with: pip install camoufox[geoip]"
        ) from e

    kwargs: Dict[str, Any] = {
        "config": dict(fingerprint_config),  # Copy to avoid mutation
        "headless": headless,
        "i_know_what_im_doing": True,  # We're managing config manually
    }

    if proxy:
        kwargs["proxy"] = proxy
    if humanize is not None:
        kwargs["humanize"] = humanize
    if addons:
        kwargs["addons"] = addons
    if enable_cache:
        kwargs["enable_cache"] = True
    if firefox_user_prefs:
        kwargs["firefox_user_prefs"] = firefox_user_prefs
    if extra_args:
        kwargs["args"] = extra_args

    opts = launch_options(**kwargs)

    # If user_data_dir is set, add persistent_context flag
    if user_data_dir:
        opts["user_data_dir"] = user_data_dir

    return opts
