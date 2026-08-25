# Avelorn — unit browser

A SvelteKit front end over the `avelorn` HTTP API: the datasheet list, and one
datasheet in full.

Its TypeScript types are generated from the API's OpenAPI document, which
FastAPI derives from the Pydantic schema the YAML validates against. A field
added to a datasheet becomes a type error here after `make types`, so no part
of a unit's shape is written down twice.

Run the API and the front end in two shells:

```
make serve      # FastAPI on :8000
make frontend   # SvelteKit on :5173
```

`/api` is proxied to the API by the dev server, so the two are one origin and
no CORS setup is involved.

Before the hooks or CI can run over it, install the toolchain once:

```
cd frontend && npm ci
```

`make frontend-lint` runs prettier and eslint, and pre-commit runs the same on
any change under `frontend/`. `make frontend-check` type-checks and builds.
`make types-check` fails when the committed `schema.d.ts` no longer matches the
Pydantic models, which is the one way the two halves can drift apart silently.
