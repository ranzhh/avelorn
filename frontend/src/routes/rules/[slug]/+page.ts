import { error } from '@sveltejs/kit';
import { api } from '$lib/api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch, url }) => {
	const { data, response } = await api(url.origin, fetch).GET('/rules/{slug}', {
		params: { path: { slug: params.slug } }
	});
	if (!data) error(response.status, `no rule entry ${params.slug}`);
	return { rule: data };
};
