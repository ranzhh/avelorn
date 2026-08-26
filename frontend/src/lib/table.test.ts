import { describe, expect, it } from 'vitest';

import type { MusteredUnit } from './api/client';
import {
	angleTo,
	arc,
	base,
	bounds,
	corners,
	identifier,
	reformed,
	room,
	separation,
	snap,
	within
} from './table';
import type { Degrees, Placed } from './table';

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

const WIDE = 125 / 25.4;
const DEEP = 100 / 25.4;

function placed(x: number, y: number, facing: Degrees = 0, block = BLOCK): Placed {
	return { id: 1, mark: 'A', block, x, y, facing, melee: '', missile: '' };
}

describe('identifier', () => {
	it('names the first blocks by letter', () => {
		expect([0, 1, 25].map(identifier)).toEqual(['A', 'B', 'Z']);
	});

	it('carries past the alphabet without repeating itself', () => {
		expect([26, 27, 51, 52].map(identifier)).toEqual(['AA', 'AB', 'AZ', 'BA']);
	});
});

describe('bounds', () => {
	it('is the block wide and deep when it faces up the table', () => {
		const { width, height } = bounds(placed(10, 10));
		expect(width).toBeCloseTo(WIDE);
		expect(height).toBeCloseTo(DEEP);
	});

	it('swaps its width and depth at a quarter turn', () => {
		const { width, height } = bounds(placed(10, 10, 90));
		expect(width).toBeCloseTo(DEEP);
		expect(height).toBeCloseTo(WIDE);
	});

	it('grows past both when the block is turned off the axis', () => {
		const { width, height } = bounds(placed(10, 10, 45));
		expect(width).toBeGreaterThan(WIDE);
		expect(height).toBeGreaterThan(WIDE);
	});

	it('names the block when it has no footprint to draw', () => {
		// The shape a list entry saved before the API measured footprints takes:
		// the key is absent rather than null, so a null check would miss it.
		const { footprint, ...saved } = BLOCK;
		void footprint;
		expect(() => bounds(placed(10, 10, 0, saved as MusteredUnit))).toThrow(
			'Elven Spearmen has no footprint'
		);
	});
});

describe('corners', () => {
	it('puts the front edge ahead of the centre when facing up', () => {
		const points = corners(placed(10, 20));
		expect(Math.min(...points.map((p) => p.y))).toBeCloseTo(20 - DEEP / 2);
	});

	it('keeps the block the same size however it is turned', () => {
		for (const facing of [0, 37, 90, 128, 210, 315]) {
			const [a, b, , d] = corners(placed(10, 20, facing));
			expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeCloseTo(DEEP);
			expect(Math.hypot(a.x - d.x, a.y - d.y)).toBeCloseTo(WIDE);
		}
	});
});

describe('separation', () => {
	it('measures the gap between the facing edges, not between the centres', () => {
		const gap = separation(placed(10, 10), placed(10, 20));
		expect(gap).toBeCloseTo(10 - DEEP);
	});

	it('is nothing once the blocks touch', () => {
		expect(separation(placed(10, 10), placed(10, 10 + DEEP))).toBeCloseTo(0);
	});

	it('is nothing when the blocks overlap', () => {
		expect(separation(placed(10, 10), placed(10, 11))).toBe(0);
	});

	it('is nothing when one block sits wholly inside another', () => {
		const huge: MusteredUnit = {
			...BLOCK,
			footprint: { files: 20, ranks: 20, width_mm: 500, depth_mm: 500 }
		};
		expect(separation(placed(10, 10), placed(10, 10, 0, huge))).toBe(0);
	});

	it('measures between the rectangles, not their bounding boxes', () => {
		// Turned 45 degrees, the bounding boxes overlap while the blocks do not.
		const gap = separation(placed(10, 10, 45), placed(16, 16, 45));
		expect(gap).toBeGreaterThan(0);
		const boxes = bounds(placed(10, 10, 45));
		const other = bounds(placed(16, 16, 45));
		expect(boxes.right).toBeGreaterThan(other.left);
	});

	it('is symmetric', () => {
		const a = placed(10, 10, 20);
		const b = placed(24, 18, 200);
		expect(separation(a, b)).toBeCloseTo(separation(b, a));
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

	it('turns with the target, at any angle', () => {
		const mover = placed(10, 2);
		expect(arc(mover, placed(10, 20, 0))).toBe('front');
		expect(arc(mover, placed(10, 20, 90))).toBe('flank');
		expect(arc(mover, placed(10, 20, 180))).toBe('rear');
		expect(arc(mover, placed(10, 20, 270))).toBe('flank');
	});

	it('takes its boundary from the block, so a wide one presents a wide front', () => {
		// Four inches across and four ahead. The block is wider than it is deep,
		// so its diagonal puts this in the front; the same models stood on end
		// call the same spot a flank.
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

	it('refuses one whose corner crosses the edge only because it is turned', () => {
		expect(within(placed(36, 2.1, 0))).toBe(true);
		expect(within(placed(36, 2.1, 45))).toBe(false);
	});
});

describe('angleTo', () => {
	it('reads zero straight up and grows clockwise', () => {
		const centre = { x: 10, y: 10 };
		expect(angleTo(centre, { x: 10, y: 4 })).toBeCloseTo(0);
		expect(angleTo(centre, { x: 16, y: 10 })).toBeCloseTo(90);
		expect(angleTo(centre, { x: 10, y: 16 })).toBeCloseTo(180);
		expect(angleTo(centre, { x: 4, y: 10 })).toBeCloseTo(270);
	});
});

describe('snap', () => {
	it('takes the nearest fifteen degrees', () => {
		expect(snap(7)).toBe(0);
		expect(snap(8)).toBe(15);
		expect(snap(96)).toBe(90);
	});

	it('wraps rather than returning 360', () => {
		expect(snap(358)).toBe(0);
		expect(snap(-10)).toBe(345);
	});
});

describe('room', () => {
	it('leaves a block where it was asked to go when nothing is there', () => {
		const wanted = placed(36, 40);
		const settled = room(wanted, []);
		expect(settled.x).toBeCloseTo(36);
		expect(settled.y).toBeCloseTo(40);
	});

	it('moves a block clear of one already standing there', () => {
		const standing = placed(36, 40);
		const settled = room({ ...placed(36, 40), id: 2 }, [standing]);
		expect(separation(settled, standing)).toBeGreaterThan(0.5);
		expect(within(settled)).toBe(true);
	});

	it('keeps the block on the table when the near edge is crowded', () => {
		const crowd = [placed(36, 40), { ...placed(30, 40), id: 2 }, { ...placed(42, 40), id: 3 }];
		const settled = room({ ...placed(36, 40), id: 4 }, crowd);
		expect(within(settled)).toBe(true);
	});
});

describe('base', () => {
	it('divides the footprint back down to one model', () => {
		const { width, depth } = base(BLOCK.footprint!);
		expect(width).toBeCloseTo(25 / 25.4);
		expect(depth).toBeCloseTo(25 / 25.4);
	});
});

describe('reformed', () => {
	const print = BLOCK.footprint!;

	it('reads the frontage off how far the edge was dragged', () => {
		// Five files of 25mm is 125mm across, so half is 62.5mm.
		expect(reformed(print, 20, 62.5 / 25.4)).toBe(5);
		expect(reformed(print, 20, 125 / 25.4)).toBe(10);
	});

	it('does not care which edge was dragged', () => {
		expect(reformed(print, 20, -125 / 25.4)).toBe(10);
	});

	it('will not go narrower than one file', () => {
		expect(reformed(print, 20, 0)).toBe(1);
		expect(reformed(print, 20, -0.01)).toBe(1);
	});

	it('will not go wider than the block has models', () => {
		expect(reformed(print, 20, 40)).toBe(20);
		expect(reformed(print, 6, 40)).toBe(6);
	});
});
