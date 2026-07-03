"""HTTP client for tow.whfb.app.

The site is a Next.js app whose pages embed their full Contentful entry.
We use the JSON data routes (`/_next/data/<buildId>/...`) instead of
parsing HTML; the build id is discovered from the homepage and refreshed
once when a redeploy invalidates it (the route then 404s).
"""

from __future__ import annotations

import json
import re
import urllib.request
from urllib.error import HTTPError

from avelorn._settings import get_settings

BASE_URL = "https://tow.whfb.app"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# Internal links on the homepage; the site's own rules index. Anchors,
# query strings and off-site links are excluded by the pattern itself.
_HREF_RE = re.compile(r'href="(/[^"#?]*)"')


class WhfbAppError(Exception):
    """The site could not be reached or returned an unusable response."""


class WhfbAppClient:
    """Fetches whfb.app pages through the Next.js JSON data routes."""

    def __init__(self, base_url: str = BASE_URL, *, contact_email: str | None = None) -> None:
        """Create a client; the build id is discovered on first use.

        Args:
            base_url: The site root to fetch from.
            contact_email: The e-mail to advertise in the User-Agent. When
                omitted, it is read from ``ATTRIBUTION_EMAIL`` in the
                environment or the ``.env`` file (see :mod:`avelorn._settings`).
        """
        self.base_url = base_url.rstrip("/")
        self._build_id: str | None = None
        email = contact_email or get_settings().attribution_email
        self._user_agent = f"ranzhh/avelorn ({email})"

    def unit_entry(self, slug: str) -> dict:
        """Fetch the fully resolved `armyListEntry` for a unit page.

        Returns:
            The entry as embedded in the page payload.

        Raises:
            WhfbAppError: The page has no unit entry (e.g. unknown slug).
        """
        props = self._page_props(f"unit/{slug}")
        entry = props.get("entry")
        if not entry:
            raise WhfbAppError(f"no unit entry in response for {slug!r}")
        return entry

    def weapons_of_war_entry(self, slug: str) -> dict:
        """Fetch the rule entry for a Weapons of War page (weapon or armour).

        Returns:
            The entry as embedded in the page payload.

        Raises:
            WhfbAppError: The page has no entry (e.g. unknown slug).
        """
        props = self._page_props(f"weapons-of-war/{slug}")
        entry = props.get("entry")
        if not entry:
            raise WhfbAppError(f"no weapons-of-war entry in response for {slug!r}")
        return entry

    def rule_entry(self, slug: str) -> dict:
        """Fetch a rule entry: a Special Rules page, or any rules page by path.

        A bare slug reads the Special Rules chapter (``special-rules/<slug>``);
        a slug containing "/" is a full page path, so core rules sections can
        be imported too (e.g. ``the-shooting-phase/firing-at-long-range``).

        Returns:
            The entry as embedded in the page payload.

        Raises:
            WhfbAppError: The page has no entry (e.g. unknown slug).
        """
        path = slug if "/" in slug else f"special-rules/{slug}"
        props = self._page_props(path)
        entry = props.get("entry")
        if not entry:
            raise WhfbAppError(f"no rule entry in response for {slug!r}")
        return entry

    def index(self) -> list[str]:
        """List every page path in the site's rules index.

        The homepage *is* the index: its HTML links every chapter,
        rules-section and army page, so the importer can enumerate pages
        (e.g. an FAQ/errata reread over every rules section) instead of
        hard-coding slugs. Static assets and file links are dropped, and
        the leading slash is stripped so each path feeds :meth:`rule_entry`
        directly. Per-unit pages (``/unit/<slug>``) are not linked here —
        they are reached from an army page via :meth:`army_unit_slugs`.

        Returns:
            The unique page paths, sorted.
        """
        html = self._get(self.base_url + "/").decode("utf-8")
        paths = set()
        for href in _HREF_RE.findall(html):
            if href == "/" or href.startswith("/_next/"):
                continue
            if "." in href.rsplit("/", 1)[-1]:  # a file, not a page
                continue
            paths.add(href.lstrip("/"))
        return sorted(paths)

    def army_unit_slugs(self, army_slug: str) -> list[str]:
        """Fetch an army page and list its units.

        Returns:
            The slug of every unit listed on the page.
        """
        props = self._page_props(f"army/{army_slug}")
        return [u["fields"]["slug"] for u in props.get("units", [])]

    def _page_props(self, path: str) -> dict:
        for attempt in (1, 2):
            if self._build_id is None:
                self._build_id = self._discover_build_id()
            url = f"{self.base_url}/_next/data/{self._build_id}/{path}.json"
            try:
                return json.loads(self._get(url))["pageProps"]
            except HTTPError as err:
                if err.code == 404 and attempt == 1:
                    self._build_id = None  # stale after a redeploy; rediscover
                    continue
                raise WhfbAppError(f"GET {url} failed: {err.code} {err.reason}") from err
        raise AssertionError("unreachable")

    def _discover_build_id(self) -> str:
        html = self._get(self.base_url + "/").decode("utf-8")
        m = _NEXT_DATA_RE.search(html)
        if not m:
            raise WhfbAppError("could not find __NEXT_DATA__ on the homepage")
        return json.loads(m.group(1))["buildId"]

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
