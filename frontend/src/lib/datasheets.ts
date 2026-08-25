import { api, type Unit } from './api/client';

// A datasheet does not change while the page is open, and an editor needs one
// every time a block is opened, so each is fetched once.
const seen = new Map<string, Unit>();

export async function datasheet(slug: string): Promise<Unit | null> {
	const cached = seen.get(slug);
	if (cached) return cached;
	const { data } = await api(window.location.origin, fetch).GET('/units/{slug}', {
		params: { path: { slug } }
	});
	if (data) seen.set(slug, data);
	return data ?? null;
}
