import { beforeEach, describe, expect, it, vi } from 'vitest';

import { entry } from './corpus';

/** Counts the requests the corpus actually makes, at the network boundary. */
function served(): { calls: string[] } {
	const calls: string[] = [];
	vi.stubGlobal('fetch', (request: Request) => {
		calls.push(new URL(request.url).pathname);
		return Promise.resolve(
			new Response(JSON.stringify({ id: 'x', name: 'X' }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
	});
	return { calls };
}

beforeEach(() => {
	vi.stubGlobal('window', { location: { origin: 'http://localhost' } });
});

describe('entry', () => {
	it('reads an entry once for a hover and the click that follows it', async () => {
		const net = served();
		const warm = entry('weapon', 'bow-of-avelorn');
		const clicked = entry('weapon', 'bow-of-avelorn');
		await Promise.all([warm, clicked]);
		expect(net.calls).toEqual(['/api/weapons/bow-of-avelorn']);
	});

	it('reads again for a name filed under another kind', async () => {
		const net = served();
		await entry('weapon', 'daiths-reaper');
		await entry('rule', 'daiths-reaper');
		expect(net.calls).toEqual(['/api/weapons/daiths-reaper', '/api/rules/daiths-reaper']);
	});

	it('keeps an entry once it has been read', async () => {
		const net = served();
		await entry('armour', 'light-armour');
		await entry('armour', 'light-armour');
		expect(net.calls).toEqual(['/api/armour/light-armour']);
	});
});
