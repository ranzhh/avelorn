import { describe, expect, it } from 'vitest';

import type { UnitOption } from './api/client';
import { byName } from './options';

const option = (id: string, name: string, kind: UnitOption['kind']): UnitOption => ({
	id,
	name,
	kind,
	scope: 'unit',
	per_model: false,
	adds_rules: [],
	removes_rules: []
});

const DWARF_WARRIORS = [
	option('shield', 'Shield', 'equipment'),
	option('veteran', 'Veteran', 'champion'),
	option('veteran-rule', 'Veteran', 'special_rule')
];

describe('byName', () => {
	it('reads a saved name back as every option printing it, as picking by name bought them', () => {
		expect(byName(DWARF_WARRIORS, ['Shield', 'Veteran'])).toEqual([
			{ id: 'shield', name: 'Shield' },
			{ id: 'veteran', name: 'Veteran' },
			{ id: 'veteran-rule', name: 'Veteran' }
		]);
	});
});
