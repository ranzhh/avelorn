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
	const DRAGON_PRINCES = [
		option('magic-items', 'Drakemaster magic items', 'other'),
		option('drakemaster', 'Drakemaster', 'champion'),
		option('standard-bearer', 'Standard Bearer', 'standard_bearer'),
		option('musician', 'Musician', 'musician')
	];

	it('gives command models the first letter of their names', () => {
		const held = keys(DRAGON_PRINCES);
		expect(held.get('drakemaster')).toBe(0);
		expect(held.get('standard-bearer')).toBe(0);
		expect(held.get('musician')).toBe(0);
	});

	it('moves past letters an earlier option holds', () => {
		expect(keys(DRAGON_PRINCES).get('magic-items')).toBe(1);
	});

	it('leaves an option without a key once its letters are all taken', () => {
		const held = keys([
			option('a', 'Ab', 'champion'),
			option('b', 'Ba', 'other'),
			option('c', 'ab', 'other')
		]);
		expect(held.has('c')).toBe(false);
	});
});
