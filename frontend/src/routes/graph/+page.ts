import type { Program } from '$lib/graph/types';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
	try {
		const response = await fetch(`${url.origin}/api/graph/volley`);
		if (!response.ok) return { program: null };
		return { program: (await response.json()) as Program };
	} catch {
		return { program: null };
	}
};
