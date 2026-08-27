import { describe, expect, it } from 'vitest';

import { FRESH, RANGE, stepped, strengthFor, summary } from './conditions';

describe('stepped', () => {
	it('moves the situational modifier by one', () => {
		expect(stepped(0, -1)).toBe(-1);
	});

	it('stops at the ends rather than running past them', () => {
		expect(stepped(RANGE.least, -1)).toBe(RANGE.least);
		expect(stepped(RANGE.most, 1)).toBe(RANGE.most);
	});
});

describe('strengthFor', () => {
	it('sends nothing for a unit that has taken no casualties', () => {
		expect(strengthFor(null, 20)).toBeNull();
	});

	it('clamps a count below the current size, which the API refuses', () => {
		expect(strengthFor(10, 20)).toBe(20);
	});

	it('leaves a depleted unit alone', () => {
		expect(strengthFor(30, 12)).toBe(30);
	});
});

describe('summary', () => {
	it('says nothing when nothing is set', () => {
		expect(summary(FRESH)).toBe('');
	});

	it('signs the situational modifier the way the rulebook prints it', () => {
		expect(summary({ ...FRESH, hit: -2 })).toBe('-2 to hit');
		expect(summary({ ...FRESH, hit: 1 })).toBe('+1 to hit');
	});

	it('gathers everything set into one line', () => {
		expect(summary({ moved: true, hit: -1, battleStrength: 30 })).toBe(
			'moved · -1 to hit · from 30'
		);
	});
});
