import type { Handle } from '@sveltejs/kit';

// A load running on the server sees only the response headers named here, and
// openapi-fetch reads both of these to decide how to parse a body.
export const handle: Handle = ({ event, resolve }) =>
	resolve(event, {
		filterSerializedResponseHeaders: (name) => name === 'content-type' || name === 'content-length'
	});
