import { error } from '@sveltejs/kit';
import { api } from '$lib/api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
	const { data, response } = await api(url.origin, fetch).GET('/units');
	if (!data) error(response.status, 'could not read the unit list');
	return { units: data };
};
