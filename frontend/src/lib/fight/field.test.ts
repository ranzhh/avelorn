import { describe, expect, it } from 'vitest';

import type { LaneUnit } from '$lib/api/client';
import { bounds, type Placed } from '$lib/table';
import princes from './fixtures/princes-charge-archers.json';
import { formed, measured } from './field';
import type { Lane } from './faces';

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
