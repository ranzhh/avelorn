import { describe, expect, it } from 'vitest';

import type { FightLanes } from '$lib/api/client';
import princes from './fixtures/princes-charge-archers.json';
import { LANES } from './faces';
import { odds } from './odds';

const lanes = princes as FightLanes;
const { breaks, result } = princes;
const total = (chances: [string, number][]) => chances.reduce((sum, [, p]) => sum + p, 0);
const near = (chances: number[]) => chances.map((p) => expect.closeTo(p, 10));
const chances = (named: [string, number][]) => named.map(([, p]) => p);
const served = (test: (typeof breaks)['target']) => [
	test.give_ground,
	test.fall_back_in_good_order,
	test.break
];

describe('the chances given each node is reached', () => {
	const given = odds(lanes);

	it('splits each Break test over taking it, its outcomes summing to 100%', () => {
		expect(given.taken).toEqual({ attacker: breaks.attacker.taken, target: breaks.target.taken });
		for (const lane of LANES) {
			const test = breaks[lane];
			expect(chances(given.outcomes[lane])).toEqual(near(served(test).map((p) => p / test.taken)));
			expect(total(given.outcomes[lane])).toBeCloseTo(1, 10);
		}
	});

	it('reads the combat result over the round fought, summing to 100%', () => {
		expect(given.shares).toEqual([
			['attacker', result.attacker_wins],
			['draw', result.draw],
			['target', result.target_wins]
		]);
		expect(total(given.shares)).toBeCloseTo(1, 10);
	});

	it('shows no outcomes of a Break test never taken', () => {
		const never = { ...breaks.attacker, taken: 0, give_ground: 0, fall_back_in_good_order: 0 };
		const drawn = { ...lanes, breaks: { ...lanes.breaks, attacker: { ...never, break: 0 } } };
		expect(chances(odds(drawn).outcomes.attacker)).toEqual([0, 0, 0]);
	});
});
