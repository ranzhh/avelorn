/**
 * The corpus, read once per entry and kept.
 *
 * Nothing under here changes while the page is open, and following a rule out of
 * two datasheets asks for the same entry twice. Keyed by kind as well as slug,
 * because a name can be filed in more than one registry -- "Daith's Reaper" is
 * both a weapon and the rule that weapon carries.
 */

import { api, type Armour, type Rule, type Unit, type Weapon } from './api/client';

export type Kind = 'unit' | 'rule' | 'weapon' | 'armour';

/** What each kind reads back, so a caller keeps its type through the cache. */
export interface Entry {
	unit: Unit;
	rule: Rule;
	weapon: Weapon;
	armour: Armour;
}

const seen = new Map<string, Entry[Kind]>();

// One call per kind rather than an indexed route: openapi-fetch types the
// request against the literal path, and a path read out of a lookup widens the
// init parameter to a union it will not accept.
async function fetched(kind: Kind, slug: string): Promise<Entry[Kind] | undefined> {
	const client = api(window.location.origin, fetch);
	const at = { params: { path: { slug } } };
	switch (kind) {
		case 'unit':
			return (await client.GET('/units/{slug}', at)).data;
		case 'rule':
			return (await client.GET('/rules/{slug}', at)).data;
		case 'weapon':
			return (await client.GET('/weapons/{slug}', at)).data;
		case 'armour':
			return (await client.GET('/armour/{slug}', at)).data;
	}
}

/**
 * Read one entry of the corpus.
 *
 * Returns the entry, or null where the route refused it. The cast is the seam
 * where the kind stops being a value and becomes a type: `fetched` returns the
 * union, and which member it is follows from the kind it was handed.
 */
export async function entry<K extends Kind>(kind: K, slug: string): Promise<Entry[K] | null> {
	const key = `${kind}:${slug}`;
	const cached = seen.get(key);
	if (cached) return cached as Entry[K];
	const found = await fetched(kind, slug);
	if (found) seen.set(key, found);
	return (found as Entry[K]) ?? null;
}
