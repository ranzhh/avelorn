import { describe, expect, it } from 'vitest';

import { pairings, ranked, roster, shade } from './matchups';
import type { Placed } from './table';

const block = (unit: string, size: number, options: string[] = [], melee = ''): Placed =>
	({
		id: 1,
		mark: 'A',
		block: { unit, size, options, points: 0, name: unit },
		x: 10,
		y: 10,
		facing: 0,
		melee,
		missile: ''
	}) as unknown as Placed;

describe('pairings', () => {
	it('never fights a block against itself', () => {
		expect(pairings(3).some((pair) => pair.row === pair.column)).toBe(false);
	});

	it('keeps both directions, since the row is the side whose win is reported', () => {
		const pairs = pairings(2);
		expect(pairs).toHaveLength(2);
		expect(pairs).toContainEqual({ row: 0, column: 1 });
		expect(pairs).toContainEqual({ row: 1, column: 0 });
	});

	it('grows as n by n minus the diagonal', () => {
		expect(pairings(5)).toHaveLength(20);
	});

	it('has nothing to resolve for a lone block', () => {
		expect(pairings(1)).toEqual([]);
	});
});

describe('roster', () => {
	it('ignores where a block stands, because a fight does not read it', () => {
		const here = block('elven-spearmen', 20);
		const there = { ...here, x: 60, y: 40, facing: 137 };
		expect(roster([there], 'engaged')).toBe(roster([here], 'engaged'));
	});

	it('changes when a block is re-sized', () => {
		expect(roster([block('elven-spearmen', 20)], 'engaged')).not.toBe(
			roster([block('elven-spearmen', 25)], 'engaged')
		);
	});

	it('changes when an option is bought', () => {
		expect(roster([block('elven-spearmen', 20, ['Shields'])], 'engaged')).not.toBe(
			roster([block('elven-spearmen', 20)], 'engaged')
		);
	});

	it('changes when the weapon in hand changes', () => {
		expect(roster([block('white-lions-of-chrace', 20, [], 'Great Weapon')], 'engaged')).not.toBe(
			roster([block('white-lions-of-chrace', 20)], 'engaged')
		);
	});

	it('changes with the stance, which decides the charge bonus', () => {
		const one = [block('elven-spearmen', 20)];
		expect(roster(one, 'charged')).not.toBe(roster(one, 'engaged'));
	});
});

describe('shade', () => {
	it('sits on the midpoint for an even matchup', () => {
		expect(shade(0.5)).toBe('color-mix(in oklab, var(--series-1) 0%, var(--neutral))');
	});

	it('leans to opposite poles for a win and the same-sized loss', () => {
		expect(shade(0.9)).toContain('--series-1');
		expect(shade(0.1)).toContain('--series-2');
	});

	it('leans further the more decided the fight is', () => {
		const near = Number(shade(0.6).match(/(\d+)%/)![1]);
		const far = Number(shade(0.95).match(/(\d+)%/)![1]);
		expect(far).toBeGreaterThan(near);
	});

	it('stops short of the pole, so the figure on top stays readable', () => {
		expect(Number(shade(1).match(/(\d+)%/)![1])).toBeLessThan(100);
	});
});

describe('ranked', () => {
	it('orders a row by how decisively it wins', () => {
		expect(ranked([0.2, null, 0.9, 0.55]).map((each) => each.column)).toEqual([2, 3, 0]);
	});

	it('drops the cells that never resolved', () => {
		expect(ranked([null, null])).toEqual([]);
	});
});
