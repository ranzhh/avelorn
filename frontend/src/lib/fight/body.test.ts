import { describe, expect, it } from 'vitest';

import type { FightBody } from '$lib/api/client';
import { redeployed } from './body';

const BODY: FightBody = {
	a: { unit: 'elven-archers', size: 10, options: [], weapon: null, frontage: 5 },
	b: { unit: 'elven-spearmen', size: 20, options: [], weapon: null, frontage: 5 },
	charge: { side: 'b', full_inches: 8, arc: 'front', reaction: 'stand-and-shoot' }
};

describe('editing a fight from its lanes', () => {
	it('edits the charger from the upper lane, whichever side of the body it is', () => {
		const edited = redeployed(BODY, 'attacker', { size: 15 });
		expect([edited.a.size, edited.b.size]).toEqual([10, 15]);
		expect(redeployed(BODY, 'target', { frontage: 10 }).a.frontage).toBe(10);
	});

	it('edits side a from the upper lane of a fight nobody charged into', () => {
		const engaged = { ...BODY, charge: null };
		expect(redeployed(engaged, 'attacker', { size: 15 }).a.size).toBe(15);
	});
});
