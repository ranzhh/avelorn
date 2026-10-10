import { beforeEach, describe, expect, it, vi } from 'vitest';

import { readBack, type Saved } from './saved';

const JSON_TYPE = { 'content-type': 'application/json' };

const SPEARMEN = {
	options: [
		{ id: 'shieldwall', name: 'Shieldwall' },
		{ id: 'veteran', name: 'Veteran' }
	]
};

const block = (unit: string, options: string[]): Saved => ({
	unit,
	name: unit,
	size: 10,
	options,
	points: 90,
	equipment: [],
	weapons: [],
	special_rules: [],
	footprint: null
});

beforeEach(() => {
	vi.stubGlobal('window', { location: { origin: 'http://localhost' } });
	vi.stubGlobal('fetch', (request: Request) => {
		const path = new URL(request.url).pathname;
		if (path === '/api/units/elven-spearmen')
			return Promise.resolve(new Response(JSON.stringify(SPEARMEN), { headers: JSON_TYPE }));
		if (path === '/api/units/sisters-of-avelorn') return Promise.reject(new TypeError('offline'));
		return Promise.resolve(
			new Response('{"detail":"no such unit"}', { status: 404, headers: JSON_TYPE })
		);
	});
});

describe('readBack', () => {
	it('sets aside a block whose datasheet cannot be read and reads back the rest', async () => {
		const spearmen = block('elven-spearmen', ['Shieldwall']);
		const missing = block('no-such-unit', ['Veteran']);
		const offline = block('sisters-of-avelorn', ['Veteran']);
		expect(await readBack([spearmen, missing, offline])).toEqual({
			blocks: [{ ...spearmen, options: [{ id: 'shieldwall', name: 'Shieldwall' }] }],
			unread: [missing, offline]
		});
	});
});
