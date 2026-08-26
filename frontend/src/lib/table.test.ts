import { describe, expect, it } from 'vitest';

import type { MusteredUnit } from './api/client';
import { arc, extent, separation, within } from './table';
import type { Facing, Placed } from './table';

// Twenty models five wide on 25mm bases: 125mm across, 100mm deep, so a block
// a shade under 5" by 4". Wide enough that its front and flank arcs differ.
const BLOCK: MusteredUnit = {
	unit: 'elven-spearmen',
	name: 'Elven Spearmen',
	size: 20,
	options: [],
	points: 160,
	equipment: [],
	weapons: [],
	special_rules: [],
	footprint: { files: 5, ranks: 4, width_mm: 125, depth_mm: 100 }
};

function placed(x: number, y: number, facing: Facing = 0, block = BLOCK): Placed {
	return { id: 1, block, x, y, facing, melee: '', missile: '' };
}

describe('extent', () => {
	it('is the block wide and deep when it faces up the table', () => {
		const { width, height } = extent(placed(10, 10));
		expect(width).toBeCloseTo(125 / 25.4);
		expect(height).toBeCloseTo(100 / 25.4);
	});

	it('swaps its width and depth when the block faces sideways', () => {
		const { width, height } = extent(placed(10, 10, 90));
		expect(width).toBeCloseTo(100 / 25.4);
		expect(height).toBeCloseTo(125 / 25.4);
	});
});

describe('separation', () => {
	it('measures the gap between the facing edges, not between the centres', () => {
		// Two blocks 4" deep, centres 10" apart: 2" of each block, 6" of gap.
		const gap = separation(placed(10, 10), placed(10, 20));
		expect(gap).toBeCloseTo(10 - 100 / 25.4);
	});

	it('is nothing once the blocks touch', () => {
		const depth = 100 / 25.4;
		expect(separation(placed(10, 10), placed(10, 10 + depth))).toBeCloseTo(0);
	});

	it('is nothing when the blocks overlap', () => {
		expect(separation(placed(10, 10), placed(10, 11))).toBe(0);
	});
});

describe('arc', () => {
	it('names the front when the mover stands ahead of a block facing up', () => {
		expect(arc(placed(10, 2), placed(10, 20))).toBe('front');
	});

	it('names the rear when the mover stands behind it', () => {
		expect(arc(placed(10, 40), placed(10, 20))).toBe('rear');
	});

	it('names a flank when the mover stands beside it', () => {
		expect(arc(placed(30, 20), placed(10, 20))).toBe('flank');
	});

	it('turns with the target: the same spot is a flank once it wheels', () => {
		const mover = placed(10, 2);
		expect(arc(mover, placed(10, 20, 0))).toBe('front');
		expect(arc(mover, placed(10, 20, 90))).toBe('flank');
		expect(arc(mover, placed(10, 20, 180))).toBe('rear');
	});

	it('takes its boundary from the block, so a wide one presents a wide front', () => {
		// Diagonally off the front-right corner, 4" across and 4" ahead. The
		// block is wider than it is deep, so its diagonal puts this in the front;
		// the same twenty models stood on end call the same spot a flank.
		const mover = placed(14, 16);
		expect(arc(mover, placed(10, 20, 0))).toBe('front');
		const onEnd: MusteredUnit = {
			...BLOCK,
			footprint: { files: 4, ranks: 5, width_mm: 100, depth_mm: 125 }
		};
		expect(arc(mover, placed(10, 20, 0, onEnd))).toBe('flank');
	});
});

describe('within', () => {
	it('accepts a block standing clear of the edges', () => {
		expect(within(placed(36, 24))).toBe(true);
	});

	it('refuses one hanging off the table', () => {
		expect(within(placed(1, 24))).toBe(false);
		expect(within(placed(36, 47.5))).toBe(false);
	});
});
