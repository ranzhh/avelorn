import createClient from 'openapi-fetch';
import type { paths } from './schema';

/**
 * A client for the Avelorn API, addressed through the app's own origin.
 *
 * `/api` is proxied to the FastAPI app by the dev server (vite.config.ts).
 * The origin is spelled out because openapi-fetch builds a `Request`, and that
 * rejects a relative URL when a load runs on the server.
 */
export const api = (origin: string, fetch: typeof globalThis.fetch) =>
	createClient<paths>({ baseUrl: `${origin}/api`, fetch });

export type Unit = paths['/units/{slug}']['get']['responses'][200]['content']['application/json'];
export type Rule = paths['/rules/{slug}']['get']['responses'][200]['content']['application/json'];
export type UnitSummary =
	paths['/units']['get']['responses'][200]['content']['application/json'][number];

export type MusteredUnit =
	paths['/muster']['post']['responses'][200]['content']['application/json'];
export type UnitOption = NonNullable<Unit['options']>[number];
export type Wieldable = MusteredUnit['weapons'][number];

export type FightReport = paths['/fight']['post']['responses'][200]['content']['application/json'];
export type FightSide = FightReport['a'];

export type VolleyReport =
	paths['/volley']['post']['responses'][200]['content']['application/json'];
