import { describe, expect, it } from 'vitest';

import type { UnitSummary } from './api/client';
import { fielded, listing, matches, reorder, sizeRange } from './listing';
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
		expect(ordered.map(fielded)).toEqual([45, 50, 80, 90]);
	});

	it('reverses when descending', () => {
		const ordered = listing(CORPUS, '', { column: 'points', descending: true });
		expect(ordered.map(fielded)).toEqual([90, 80, 50, 45]);
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
		expect(sizeRange({ min: 5, max: null })).toBe('5+');
		expect(sizeRange({ min: 3 })).toBe('3+');
	});

	it('prints a capped range as both ends', () => {
		expect(sizeRange({ min: 3, max: 5 })).toBe('3–5');
	});

	it('prints a fixed size as one number', () => {
		expect(sizeRange({ min: 1, max: 1 })).toBe('1');
	});
});

describe('fielded', () => {
	it('costs the smallest legal unit, not one model', () => {
		// Elven Archers are 9 a model with a printed minimum of 5.
		expect(fielded(CORPUS[0])).toBe(45);
	});

	it('follows the datasheet’s own minimum', () => {
		expect(fielded(CORPUS[1])).toBe(80);
		expect(fielded(CORPUS[3])).toBe(50);
	});
});

describe('listing by points', () => {
	it('orders by what a unit costs to field, not by its per-model price', () => {
		// Dwarf Warriors are cheaper a model than Elven Archers, dearer to field.
		const ordered = listing(CORPUS, '', { column: 'points', descending: false });
		expect(ordered.map((each) => each.name)).toEqual([
			'Elven Archers',
			'Great Eagle',
			'Dwarf Warriors',
			'Ellyrian Reavers'
		]);
	});
});
