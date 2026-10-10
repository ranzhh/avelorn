import { beforeEach, describe, expect, it } from 'vitest';

import type { FightBody, FightReport, MusteredUnit } from './api/client';
import { battle } from './battle.svelte';
import type { Placed } from './table';

const BLOCK: MusteredUnit = {
	unit: 'elven-spearmen',
	name: 'Elven Spearmen',
	size: 5,
	options: [],
	points: 50,
	equipment: [],
	weapons: [],
	special_rules: [],
	footprint: { files: 5, ranks: 1, width_mm: 125, depth_mm: 25 }
};

function placed(id: number, x: number): Placed {
	return { id, mark: 'A', block: BLOCK, x, y: 10, facing: 0, melee: '', missile: '' };
}

const BODY = { a: {}, b: {}, charge: null } as unknown as FightBody;
const REPORT = {} as FightReport;

describe('the resolution the table keeps', () => {
	beforeEach(() => {
		battle.placed = [placed(1, 10), placed(2, 20), placed(3, 30)];
		battle.resolved = { action: 'fight', between: [1, 2], body: BODY, report: REPORT };
	});

	it('outlives a block grabbed and let go where it stood, and any block outside it', () => {
		battle.amend(1, { x: 10, y: 10 });
		battle.amend(3, { x: 40 });
		battle.remove(3);
		expect(battle.resolved).not.toBeNull();
	});

	it('goes with a block of its own that moves', () => {
		battle.amend(2, { x: 25 });
		expect(battle.resolved).toBeNull();
	});

	it('goes with a block of its own that leaves the table', () => {
		battle.remove(1);
		expect(battle.resolved).toBeNull();
	});
});
