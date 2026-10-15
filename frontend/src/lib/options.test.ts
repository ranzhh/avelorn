import { describe, expect, it } from 'vitest';

import type { UnitOption } from './api/client';
import { byName, keys } from './options';

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

describe('keys', () => {
	const ELVEN_ARCHERS = [
		option('sentinel', 'Sentinel', 'champion'),
		option('standard-bearer', 'Standard Bearer', 'standard_bearer'),
		option('musician', 'Musician', 'musician'),
		option('magic-standard', 'Magic standard', 'magic_standard'),
		option('shields', 'Shields', 'equipment')
	];

	it('gives command models their own letters whatever they are called', () => {
		const held = keys(ELVEN_ARCHERS);
		expect(held.get('sentinel')).toEqual({ letter: 'c', at: -1, hint: 'Champion' });
		expect(held.get('standard-bearer')).toEqual({ letter: 's', at: 0 });
		expect(held.get('musician')).toEqual({ letter: 'm', at: 0 });
		expect(held.has('magic-standard')).toBe(false);
	});

	it('gives every other option a letter none of them holds', () => {
		expect(keys(ELVEN_ARCHERS).get('shields')).toEqual({ letter: 'h', at: 1 });
	});

	it('leaves an option without a key once its letters are all taken', () => {
		const held = keys([
			option('a', 'Ab', 'other'),
			option('b', 'Ba', 'other'),
			option('c', 'ab', 'other')
		]);
		expect(held.has('c')).toBe(false);
	});
});
