"""
CLI entry point for camoufox-profiles.

Usage: cfox <command> [options]
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click

# Default base directory
DEFAULT_BASE_DIR = str(Path.home() / ".camoufox-profiles")


def _get_base_dir(ctx: click.Context) -> str:
    """Get base directory from context."""
    return ctx.obj.get("base_dir", DEFAULT_BASE_DIR)


def _run_async(coro):
    """Run an async coroutine in the event loop."""
    return asyncio.run(coro)


@click.group()
@click.option(
    "--base-dir", "-d",
    default=DEFAULT_BASE_DIR,
    envvar="CFOX_BASE_DIR",
    help="Base directory for profile storage.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def main(ctx: click.Context, base_dir: str, verbose: bool) -> None:
    """Camoufox profile management CLI."""
    ctx.ensure_object(dict)
    ctx.obj["base_dir"] = base_dir

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ─── Profile commands ──────────────────────────────────────────────


@main.command()
@click.argument("name")
@click.option("--os", "target_os", default="windows", help="Target OS (windows/macos/linux).")
@click.option("--tag", "-t", multiple=True, help="Tags for the profile.")
@click.option("--notes", default="", help="Profile notes.")
@click.option("--proxy-id", default=None, help="Proxy pool entry ID to bind.")
@click.pass_context
def create(ctx: click.Context, name: str, target_os: str, tag: tuple, notes: str, proxy_id: Optional[str]) -> None:
    """Create a new profile with a fresh fingerprint."""
    async def _create():
        from .fingerprint import capture_fingerprint
        from .store import ProfileStore

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            # Resolve proxy for fingerprint generation
            proxy_dict = None
            creation_ip = None
            creation_region = None

            if proxy_id:
                from .proxy import ProxyStore
                ps = ProxyStore(store._ensure_db())
                entry = await ps.get(proxy_id)
                if entry:
                    proxy_dict = entry.to_playwright()

            # Capture fingerprint
            click.echo(f"Generating fingerprint for '{name}' (os={target_os})...")
            fp = capture_fingerprint(
                target_os=target_os,
                proxy=proxy_dict,
                geoip=True,
            )

            # Resolve creation IP/region
            try:
                from camoufox.ip import public_ip
                from camoufox.locale import get_geolocation
                if proxy_dict:
                    from camoufox.ip import Proxy
                    creation_ip = public_ip(Proxy(**proxy_dict).as_string())
                else:
                    creation_ip = public_ip()
                geo = get_geolocation(creation_ip)
                creation_region = geo.locale.region
            except Exception:
                pass

            profile = await store.create(
                name=name,
                target_os=target_os,
                fingerprint_config=fp,
                tags=list(tag),
                notes=notes,
                proxy_id=proxy_id,
                creation_ip=creation_ip,
                creation_region=creation_region,
            )

            click.echo(f"Created profile '{profile.name}' (id={profile.id[:8]})")
            click.echo(f"  OS: {profile.target_os}")
            click.echo(f"  UA: {fp.get('navigator.userAgent', 'N/A')[:60]}...")
            if creation_region:
                click.echo(f"  Region: {creation_region}")

        finally:
            await store.close()

    _run_async(_create())


@main.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag.")
@click.option("--os", "target_os", default=None, help="Filter by OS.")
@click.option("--search", "-s", default=None, help="Search name/notes.")
@click.option("--limit", default=50, help="Max results.")
@click.pass_context
def list_profiles(ctx: click.Context, tag: Optional[str], target_os: Optional[str], search: Optional[str], limit: int) -> None:
    """List all profiles."""
    async def _list():
        from .store import ProfileStore
        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profiles = await store.list(tag=tag, target_os=target_os, search=search, limit=limit)
            count = await store.count(tag=tag, target_os=target_os)

            if not profiles:
                click.echo("No profiles found.")
                return

            click.echo(f"Profiles ({len(profiles)}/{count}):\n")
            for p in profiles:
                ua_short = p.fingerprint_config.get("navigator.userAgent", "")[:40]
                status = "✓" if p.warmup_completed else "○"
                proxy_info = f" proxy={p.proxy_id[:8]}" if p.proxy_id else ""
                region = f" [{p.creation_region}]" if p.creation_region else ""
                click.echo(
                    f"  {status} {p.name:<20} os={p.target_os:<7} "
                    f"sessions={p.total_sessions:<4}{proxy_info}{region}"
                )
                click.echo(f"    id={p.id[:8]}  ua={ua_short}...")
        finally:
            await store.close()

    _run_async(_list())


@main.command()
@click.argument("name")
@click.option("--drift/--no-drift", default=True, help="Enable/disable drift engine.")
@click.option("--headless", is_flag=True, help="Run headless.")
@click.pass_context
def launch(ctx: click.Context, name: str, drift: bool, headless: bool) -> None:
    """Launch a profile's browser interactively."""
    async def _launch():
        from .store import ProfileStore
        from .launcher import launch_profile

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await store.get_by_name(name)
            click.echo(f"Launching '{profile.name}' (drift={'on' if drift else 'off'})...")

            async with launch_profile(
                profile, store, drift=drift, headless=headless
            ) as context:
                click.echo("Browser is running. Press Ctrl+C to close.")
                page = context.pages[0] if context.pages else await context.new_page()

                # Keep browser open until user interrupts
                try:
                    while True:
                        await asyncio.sleep(1)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    click.echo("\nClosing browser...")
        finally:
            await store.close()

    try:
        _run_async(_launch())
    except KeyboardInterrupt:
        click.echo("Done.")


@main.command()
@click.argument("name")
@click.option("--max-sites", default=10, help="Max sites to visit.")
@click.option("--headless/--no-headless", default=True, help="Run headless.")
@click.pass_context
def warmup(ctx: click.Context, name: str, max_sites: int, headless: bool) -> None:
    """Warmup a profile by visiting popular sites."""
    async def _warmup():
        from .store import ProfileStore
        from .warmup import warmup_profile
        from .launcher import launch_profile

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await store.get_by_name(name)
            click.echo(f"Warming up '{profile.name}' (max_sites={max_sites})...")

            async with launch_profile(profile, store, headless=headless) as context:
                report = await warmup_profile(context, max_sites=max_sites)
                click.echo(
                    f"Warmup complete: {report.successful_visits}/{report.total_visits} sites visited"
                )

                # Mark warmup completed
                await store.update_v2_fields(profile.id, warmup_completed=True)

        finally:
            await store.close()

    _run_async(_warmup())


@main.command()
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete(ctx: click.Context, name: str, yes: bool) -> None:
    """Delete a profile and its browser data."""
    async def _delete():
        from .store import ProfileStore
        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await store.get_by_name(name)
            if not yes:
                click.confirm(f"Delete profile '{name}' (id={profile.id[:8]})?", abort=True)
            await store.delete(profile.id)
            click.echo(f"Deleted profile '{name}'")
        finally:
            await store.close()

    _run_async(_delete())


@main.command()
@click.argument("name")
@click.pass_context
def health(ctx: click.Context, name: str) -> None:
    """Run health checks on a profile."""
    async def _health():
        from .store import ProfileStore
        from .health import check_profile_health

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await store.get_by_name(name)

            # Get installed Firefox version
            try:
                from .drift import _get_installed_firefox_version
                ff_ver = _get_installed_firefox_version()
            except Exception:
                ff_ver = None

            # Get current IP info for null-proxy profiles
            current_ip = None
            current_region = None
            if not profile.proxy_id and not profile.proxy:
                try:
                    from camoufox.ip import public_ip
                    from camoufox.locale import get_geolocation
                    current_ip = public_ip()
                    geo = get_geolocation(current_ip)
                    current_region = geo.locale.region
                except Exception:
                    pass

            report = await check_profile_health(
                profile,
                installed_ff_version=ff_ver,
                current_public_ip=current_ip,
                current_region=current_region,
            )

            # Display results
            status_icon = {"healthy": "✓", "warning": "⚠", "critical": "✗"}.get(report.status, "?")
            click.echo(f"\nHealth: {status_icon} {report.status.upper()} — {profile.name}\n")

            for check in report.checks:
                icon = "✓" if check.passed else ("✗" if check.severity == "critical" else "⚠")
                click.echo(f"  {icon} {check.check_name}: {check.message or 'OK'}")

            if report.recommendations:
                click.echo(f"\nRecommendations:")
                for rec in report.recommendations:
                    click.echo(f"  → {rec}")

        finally:
            await store.close()

    _run_async(_health())


# ─── Proxy commands ────────────────────────────────────────────────


@main.group()
def proxy() -> None:
    """Manage the proxy pool."""
    pass


@proxy.command("add")
@click.argument("server")
@click.option("--username", "-u", default=None, help="Proxy username.")
@click.option("--password", "-p", default=None, help="Proxy password.")
@click.option("--tag", "-t", multiple=True, help="Tags for the proxy.")
@click.pass_context
def proxy_add(ctx: click.Context, server: str, username: Optional[str], password: Optional[str], tag: tuple) -> None:
    """Add a proxy to the pool."""
    async def _add():
        from .store import ProfileStore
        from .proxy import ProxyStore

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            ps = ProxyStore(store._ensure_db())
            entry = await ps.add(server, username, password, list(tag))
            click.echo(f"Added proxy: {entry.id[:8]} — {server}")
        finally:
            await store.close()

    _run_async(_add())


@proxy.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag.")
@click.option("--alive-only", is_flag=True, help="Show only alive proxies.")
@click.pass_context
def proxy_list(ctx: click.Context, tag: Optional[str], alive_only: bool) -> None:
    """List proxies in the pool."""
    async def _list():
        from .store import ProfileStore
        from .proxy import ProxyStore

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            ps = ProxyStore(store._ensure_db())
            proxies = await ps.list(tag=tag, alive_only=alive_only)

            if not proxies:
                click.echo("No proxies found.")
                return

            click.echo(f"Proxies ({len(proxies)}):\n")
            for p in proxies:
                status = "✓" if p.is_alive else "✗"
                latency = f"{p.last_latency_ms}ms" if p.last_latency_ms else "?"
                ip_info = f"ip={p.last_ip}" if p.last_ip else ""
                click.echo(f"  {status} {p.id[:8]} {p.server:<40} {latency:<8} {ip_info}")
        finally:
            await store.close()

    _run_async(_list())


@proxy.command("check")
@click.option("--concurrency", "-c", default=5, help="Max concurrent checks.")
@click.pass_context
def proxy_check(ctx: click.Context, concurrency: int) -> None:
    """Health check all proxies."""
    async def _check():
        from .store import ProfileStore
        from .proxy import ProxyStore

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            ps = ProxyStore(store._ensure_db())
            click.echo("Checking proxy health...")
            results = await ps.check_all(concurrency=concurrency)

            alive = sum(1 for r in results if r.is_alive)
            click.echo(f"\nResults: {alive}/{len(results)} alive")
        finally:
            await store.close()

    _run_async(_check())


@proxy.command("bind")
@click.argument("profile_name")
@click.argument("proxy_id")
@click.pass_context
def proxy_bind(ctx: click.Context, profile_name: str, proxy_id: str) -> None:
    """Bind a proxy pool entry to a profile."""
    async def _bind():
        from .manager import ProfileManager

        pm = ProfileManager(_get_base_dir(ctx))
        await pm.initialize()
        try:
            profile = await pm.get_profile_by_name(profile_name)
            await pm.bind_proxy(profile.id, proxy_id)
            click.echo(f"Bound proxy {proxy_id[:8]} → profile '{profile_name}'")
        finally:
            await pm.close()

    _run_async(_bind())


# ─── Export / Import ───────────────────────────────────────────────


@main.command("export")
@click.argument("name")
@click.argument("output_path")
@click.option("--password", "-p", default=None, help="Encrypt with AES-256.")
@click.pass_context
def export_cmd(ctx: click.Context, name: str, output_path: str, password: Optional[str]) -> None:
    """Export a profile to a ZIP archive."""
    async def _export():
        from .store import ProfileStore
        from .transfer import export_profile

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await store.get_by_name(name)
            path = await export_profile(profile, output_path, password)
            click.echo(f"Exported '{name}' to {path}")
        finally:
            await store.close()

    _run_async(_export())


@main.command("import")
@click.argument("zip_path")
@click.option("--name", default=None, help="Override profile name.")
@click.option("--password", "-p", default=None, help="Decryption password.")
@click.pass_context
def import_cmd(ctx: click.Context, zip_path: str, name: Optional[str], password: Optional[str]) -> None:
    """Import a profile from a ZIP archive."""
    async def _import():
        from .store import ProfileStore
        from .transfer import import_profile

        store = ProfileStore(_get_base_dir(ctx))
        await store.initialize()

        try:
            profile = await import_profile(store, zip_path, name, password)
            click.echo(f"Imported profile '{profile.name}' (id={profile.id[:8]})")
        finally:
            await store.close()

    _run_async(_import())


if __name__ == "__main__":
    main()
