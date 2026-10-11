import { describe, expect, it } from 'vitest';

import type { FightLanes } from '$lib/api/client';
import princes from './fixtures/princes-charge-archers.json';
import { LANES } from './faces';
import { odds } from './odds';

const lanes = princes as FightLanes;
const { breaks, charge, result } = princes;
const total = (chances: [string, number][]) => chances.reduce((sum, [, p]) => sum + p, 0);
const near = (chances: number[]) => chances.map((p) => expect.closeTo(p, 10));
const chances = (named: [string, number][]) => named.map(([, p]) => p);
const served = (test: (typeof breaks)['target']) => [
	test.give_ground,
	test.fall_back_in_good_order,
	test.break
];

describe('the chances given each node is reached', () => {
	const conditional = odds(lanes, 'conditional');

	it('splits each Break test over taking it, its outcomes summing to 100%', () => {
		expect(conditional.taken).toEqual({
			attacker: breaks.attacker.taken,
			target: breaks.target.taken
		});
		for (const lane of LANES) {
			const test = breaks[lane];
			expect(chances(conditional.outcomes[lane])).toEqual(
				near(served(test).map((p) => p / test.taken))
			);
			expect(total(conditional.outcomes[lane])).toBeCloseTo(1, 10);
		}
	});

	it('reads the combat result over the round fought, summing to 100%', () => {
		expect(conditional.shares).toEqual([
			['attacker', result.attacker_wins],
			['draw', result.draw],
			['target', result.target_wins]
		]);
		expect(total(conditional.shares)).toBeCloseTo(1, 10);
	});

	it('shows no outcomes of a Break test never taken', () => {
		const never = { ...breaks.attacker, taken: 0, give_ground: 0, fall_back_in_good_order: 0 };
		const drawn = { ...lanes, breaks: { ...lanes.breaks, attacker: { ...never, break: 0 } } };
		expect(chances(odds(drawn, 'conditional').outcomes.attacker)).toEqual([0, 0, 0]);
	});
});

describe('the chances from the start of the charge', () => {
	it('weighs each chance by the charge reaching, the result summing to 100% with it falling short', () => {
		const marginal = odds(lanes, 'marginal');
		const reach = charge.reaches;

		for (const lane of LANES) {
			expect(marginal.taken[lane]).toBeCloseTo(reach * breaks[lane].taken, 10);
			expect(chances(marginal.outcomes[lane])).toEqual(
				near(served(breaks[lane]).map((p) => reach * p))
			);
		}
		expect(marginal.shares).toEqual([
			['attacker', expect.closeTo(reach * result.attacker_wins, 10)],
			['draw', expect.closeTo(reach * result.draw, 10)],
			['target', expect.closeTo(reach * result.target_wins, 10)],
			['short', expect.closeTo(1 - reach, 10)]
		]);
		expect(total(marginal.shares)).toBeCloseTo(1, 10);
	});

	it.each([
		['a charge sure to reach', { ...charge, reaches: 1 }],
		['a fight nobody charged into', null]
	])('reads %s as the round fought, no share falling short', (_, sure) => {
		const marginal = odds({ ...lanes, charge: sure } as FightLanes, 'marginal');

		expect(marginal.taken).toEqual({
			attacker: breaks.attacker.taken,
			target: breaks.target.taken
		});
		expect(chances(marginal.outcomes.target)).toEqual(served(breaks.target));
		expect(marginal.shares.map(([way]) => way)).toEqual(['attacker', 'draw', 'target']);
		expect(total(marginal.shares)).toBeCloseTo(1, 10);
	});
});
