import { describe, expect, it } from 'vitest';

import type { UnitSummary } from './api/client';
import { listing, matches, reorder, sizeRange } from './listing';
import type { Order } from './listing';

const unit = (
	name: string,
	points: number,
	troop_type: string,
	armies: string[],
	min = 5,
	max: number | null = null
): UnitSummary =>
	({
		id: name.toLowerCase().replaceAll(' ', '-'),
		name,
		points,
		troop_type,
		armies,
		unit_size: { min, max }
	}) as UnitSummary;

const CORPUS = [
	unit('Elven Archers', 9, 'Regular Infantry', ['high-elf-realms']),
	unit('Dwarf Warriors', 8, 'Heavy Infantry', ['dwarfen-mountain-holds'], 10),
	unit('Ellyrian Reavers', 18, 'Light Cavalry', ['high-elf-realms']),
	unit('Great Eagle', 50, 'Monstrous Beast', ['high-elf-realms', 'wood-elf-realms'], 1, 1)
];

const ASC: Order = { column: 'name', descending: false };

describe('matches', () => {
	it('finds a datasheet by its troop type, not only its name', () => {
		expect(matches(CORPUS[2], 'cavalry')).toBe(true);
	});

	it('finds one by the army fielding it', () => {
		expect(matches(CORPUS[1], 'dwarfen')).toBe(true);
		expect(matches(CORPUS[0], 'dwarfen')).toBe(false);
	});

	it('ignores case and surrounding space', () => {
		expect(matches(CORPUS[0], '  ELVEN ')).toBe(true);
	});

	it('keeps everything when nothing is typed', () => {
		expect(CORPUS.every((each) => matches(each, ''))).toBe(true);
	});
});

describe('listing', () => {
	it('orders by a numeric column numerically, not as text', () => {
		const ordered = listing(CORPUS, '', { column: 'points', descending: false });
		expect(ordered.map((each) => each.points)).toEqual([8, 9, 18, 50]);
	});

	it('reverses when descending', () => {
		const ordered = listing(CORPUS, '', { column: 'points', descending: true });
		expect(ordered.map((each) => each.points)).toEqual([50, 18, 9, 8]);
	});

	it('breaks ties on name so the order is total', () => {
		const tied = [
			unit('Bravo', 8, 'Regular Infantry', ['x']),
			unit('Alpha', 8, 'Regular Infantry', ['x'])
		];
		for (const descending of [false, true]) {
			const ordered = listing(tied, '', { column: 'points', descending });
			expect(ordered.map((each) => each.name)).toEqual(['Alpha', 'Bravo']);
		}
	});

	it('filters before ordering', () => {
		const ordered = listing(CORPUS, 'high-elf', ASC);
		expect(ordered.map((each) => each.name)).toEqual([
			'Ellyrian Reavers',
			'Elven Archers',
			'Great Eagle'
		]);
	});

	it('orders by the size a datasheet starts at', () => {
		const ordered = listing(CORPUS, '', { column: 'size', descending: false });
		expect(ordered.map((each) => each.unit_size.min)).toEqual([1, 5, 5, 10]);
	});
});

describe('reorder', () => {
	it('starts a new column ascending', () => {
		expect(reorder({ column: 'name', descending: true }, 'points')).toEqual({
			column: 'points',
			descending: false
		});
	});

	it('reverses the column already sorted', () => {
		expect(reorder({ column: 'points', descending: false }, 'points')).toEqual({
			column: 'points',
			descending: true
		});
	});
});

describe('sizeRange', () => {
	it('prints an open range as a minimum', () => {
		expect(sizeRange(CORPUS[0])).toBe('5+');
	});

	it('prints a bounded range as both ends', () => {
		expect(sizeRange(CORPUS[3])).toBe('1–1');
	});
});
