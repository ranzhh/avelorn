"""Import unit data from tow.whfb.app (the Old World online rules index).

The site is a Next.js app over a Contentful space, and every unit page
embeds its fully resolved entry as JSON — so this importer consumes
structured data, not scraped HTML:

- `client` fetches entries via the `/_next/data/<buildId>/...` JSON routes,
  discovering the build id from the homepage and refreshing it when a
  redeploy invalidates it.
- `richtext` walks the Contentful rich-text fields (equipment, special
  rules, options) that link to `rule` entries.
- `parse` maps an `armyListEntry` payload onto the unit schema. It never
  guesses silently: unparseable required fields raise, and option lines
  that match no known pattern come through as `kind: other` with the raw
  text plus a warning, so the human reviewing the YAML diff sees them.
- `yamlout` serializes a `Unit` in the hand-authored style used under
  `data/`.

The CLI lives in ``scripts/import_whfb_app.py``:

    uv run python scripts/import_whfb_app.py unit elven-archers
    uv run python scripts/import_whfb_app.py army high-elf-realms
"""
