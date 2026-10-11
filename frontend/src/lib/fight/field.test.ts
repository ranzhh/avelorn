import { describe, expect, it } from 'vitest';

import type { LaneUnit } from '$lib/api/client';
import { TABLE, bounds, type Placed } from '$lib/table';
import princes from './fixtures/princes-charge-archers.json';
import { CROP, cropped, formed, measured, standable } from './field';
import { LANES, type Box, type Lane } from './faces';

const INCH = 25.4;
const { attacker: dragons, target: archers } = princes.units as Record<Lane, LaneUnit>;

/** A block of the unit standing at `x`, `y`, formed up as the fixture fields it. */
function standing(unit: LaneUnit, x: number, y: number, facing: number): Placed {
	const base = unit.base!;
	return {
		id: unit === dragons ? 1 : 2,
		mark: unit === dragons ? 'A' : 'B',
		x,
		y,
		facing,
		melee: '',
		missile: '',
		block: {
			unit: unit.unit,
			name: unit.name,
			size: unit.size,
			options: [],
			points: 0,
			equipment: [],
			weapons: [],
			special_rules: [],
			footprint: {
				files: unit.frontage,
				ranks: unit.ranks,
				width_mm: unit.frontage * base.width_mm,
				depth_mm: unit.ranks * base.depth_mm
			}
		}
	};
}

const DRAGONS = { half: (2 * 60) / INCH / 2 };
const ARCHERS = { halfWidth: (5 * 25) / INCH / 2, halfDepth: (2 * 25) / INCH / 2 };

describe('the battlefield read off the blocks', () => {
	const target = standing(archers, 36, 30, 0);
	const front = 30 - ARCHERS.halfDepth;

	it('rounds the gap to whole inches and takes the arc the attacker stands in', () => {
		const ahead = standing(dragons, 36, front - 12.4 - DRAGONS.half, 180);
		const beside = standing(dragons, 36 + ARCHERS.halfWidth + 6.6 + DRAGONS.half, 30, 270);

		expect(measured({ attacker: ahead, target })).toEqual({ full_inches: 12, arc: 'front' });
		expect(measured({ attacker: beside, target })).toEqual({ full_inches: 7, arc: 'flank' });
	});

	it('re-forms a block as its unit is fielded, its front rank where it stood', () => {
		const deeper = formed(target, { ...archers, frontage: 2, ranks: 5 });
		const box = bounds(deeper);

		expect(box.top).toBeCloseTo(front);
		expect(box.width).toBeCloseTo((2 * 25) / INCH);
		expect(box.height).toBeCloseTo((5 * 25) / INCH);
	});
});

describe('the crop of the table', () => {
	const holds = (crop: Box, block: Placed) => {
		const box = bounds(block);
		return (
			box.left >= crop.x &&
			box.right <= crop.x + crop.width &&
			box.top >= crop.y &&
			box.bottom <= crop.y + crop.height
		);
	};

	it("shows both blocks with room round them, in the crop's proportions", () => {
		const crop = cropped({
			attacker: standing(dragons, 36, 15, 180),
			target: standing(archers, 36, 31, 0)
		});

		expect(crop.width / crop.height).toBeCloseTo(CROP.width / CROP.height);
		expect(crop.y).toBeCloseTo(15 - DRAGONS.half - CROP.margin);
		expect(crop.y + crop.height).toBeCloseTo(31 + ARCHERS.halfDepth + CROP.margin);
	});

	it('stays on the table in a corner, still showing both blocks', () => {
		const blocks = { attacker: standing(dragons, 8, 30, 180), target: standing(archers, 4, 46, 0) };
		const crop = cropped(blocks);

		expect(crop.x).toBe(0);
		expect(crop.y + crop.height).toBeCloseTo(TABLE.depth);
		expect(LANES.filter((lane) => !holds(crop, blocks[lane]))).toEqual([]);
	});
});

describe('a block dragged across the crop', () => {
	it('stands only on the table, inside the crop and clear of the other block', () => {
		const target = standing(archers, 36, 31, 0);
		const crop = { x: -4, y: 6, width: 60, height: 32 };
		const at = (x: number, y: number) => standable(standing(dragons, x, y, 180), target, crop);

		expect([at(36, 15), at(36, 29), at(36, 7), at(1, 15)]).toEqual([true, false, false, false]);
	});
});
