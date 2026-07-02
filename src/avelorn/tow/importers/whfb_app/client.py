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

BASE_URL = "https://tow.whfb.app"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_USER_AGENT = "avelorn-importer/0.1 (unit data importer)"


class WhfbAppError(Exception):
    """The site could not be reached or returned an unusable response."""


class WhfbAppClient:
    """Fetches whfb.app pages through the Next.js JSON data routes."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        """Create a client; the build id is discovered on first use."""
        self.base_url = base_url.rstrip("/")
        self._build_id: str | None = None

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

    def special_rule_entry(self, slug: str) -> dict:
        """Fetch the rule entry for a Special Rules page.

        Returns:
            The entry as embedded in the page payload.

        Raises:
            WhfbAppError: The page has no entry (e.g. unknown slug).
        """
        props = self._page_props(f"special-rules/{slug}")
        entry = props.get("entry")
        if not entry:
            raise WhfbAppError(f"no special-rules entry in response for {slug!r}")
        return entry

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
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
