import { describe, expect, it } from 'vitest';

import type { VolleyLanes } from '$lib/api/client';
import archers from './fixtures/archers-shoot-woodsmen.json';
import { left, type Measure } from './faces';
import { VIEWS } from './odds';
import { drawVolley } from './volley';

const lanes = archers as VolleyLanes;
const measure: Measure = (text) => text.length * 7;

describe('a volley drawn in lanes', () => {
	it('leaves the target each count of models its casualties leave it', () => {
		const { casualties } = lanes.volley;
		const standing = left(lanes.units.target.size, casualties);

		casualties.distribution.forEach((p, k) => {
			const models = lanes.units.target.size - (casualties.least + k);
			expect(standing.distribution[models - standing.least]).toBe(p);
		});
		expect(standing.mean).toBeCloseTo(lanes.units.target.size - casualties.mean);
	});

	it.each(VIEWS)('reads the Panic test outcomes %s', (view) => {
		const outcomes = drawVolley(lanes, measure, null, view).nodes.flatMap((node) =>
			node.kind === 'outcome' ? [node.p] : []
		);
		const total = outcomes.reduce((sum, p) => sum + p, 0);

		expect(outcomes).toHaveLength(3);
		expect(total).toBeCloseTo(view === 'conditional' ? 1 : lanes.panic.taken);
	});

	it.each([null, 'volley', 'panic', 'unit:attacker', 'pill:target:1'])(
		'keeps every card clear of the others with %s open',
		(open) => {
			const boxes = drawVolley(lanes, measure, open).nodes.map((node) => node.box);
			const overlaps = boxes.flatMap((a, i) =>
				boxes
					.slice(i + 1)
					.filter(
						(b) =>
							a.x < b.x + b.width &&
							b.x < a.x + a.width &&
							a.y < b.y + b.height &&
							b.y < a.y + a.height
					)
			);

			expect(overlaps).toEqual([]);
		}
	);
});
