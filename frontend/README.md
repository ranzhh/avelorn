# Avelorn — unit browser

A SvelteKit front end over the `avelorn` HTTP API: the datasheet list, and one
datasheet in full.

`openapi.json` is committed: it is the API's contract, derived by FastAPI from
the Pydantic schema the YAML validates against, and a change to a datasheet
shows up there as a diff you can read. The TypeScript is generated from it by
`npm run types`, which every other script runs first, so a fresh clone needs
npm and nothing else. `make types` rewrites the document itself, and is what
you run after changing a model.

Run the whole stack in containers:

```
make up
```

Or the two processes natively, in two shells:

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
