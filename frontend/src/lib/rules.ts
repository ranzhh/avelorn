import { api, type Rule } from './api/client';

// A rule entry does not change while the page is open, and following a rule
// from two datasheets asks for the same one twice.
const seen = new Map<string, Rule>();

export async function rule(slug: string): Promise<Rule | null> {
	const cached = seen.get(slug);
	if (cached) return cached;
	const { data } = await api(window.location.origin, fetch).GET('/rules/{slug}', {
		params: { path: { slug } }
	});
	if (data) seen.set(slug, data);
	return data ?? null;
}
