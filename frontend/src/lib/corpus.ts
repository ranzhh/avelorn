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

const seen = new Map<string, Promise<Entry[Kind] | undefined>>();

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
 * Returns the entry, or null where the route refused it. What is kept is the
 * read rather than the result, so a hover that warms an entry and the click
 * that follows it wait on one request between them.
 *
 * The cast is the seam where the kind stops being a value and becomes a type:
 * `fetched` returns the union, and which member it is follows from the kind it
 * was handed.
 */
export function entry<K extends Kind>(kind: K, slug: string): Promise<Entry[K] | null> {
	const key = `${kind}:${slug}`;
	let reading = seen.get(key);
	if (!reading) {
		reading = fetched(kind, slug);
		// A read that threw is not an answer. Drop it so the next caller asks again.
		reading.catch(() => seen.delete(key));
		seen.set(key, reading);
	}
	return reading.then((found) => (found as Entry[K]) ?? null);
}
