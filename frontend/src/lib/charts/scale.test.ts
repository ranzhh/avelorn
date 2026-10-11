import { describe, expect, it } from 'vitest';

import { band, labelEvery, percent, percents, ticks } from './scale';

describe('band', () => {
	it('drops the negligible tail', () => {
		expect(band([0.5, 0.3, 0.2, 0, 0, 0])).toEqual({ from: 0, masses: [0.5, 0.3, 0.2] });
	});

	it('drops a negligible head and says where it starts', () => {
		expect(band([0, 0, 0.6, 0.4])).toEqual({ from: 2, masses: [0.6, 0.4] });
	});

	it('keeps a negligible gap in the middle, so the axis stays continuous', () => {
		// Dropping index 1 would stand 0 beside 2 and misstate the shape.
		expect(band([0.5, 0, 0.5])).toEqual({ from: 0, masses: [0.5, 0, 0.5] });
	});

	it('survives a distribution with nothing in it', () => {
		expect(band([0, 0, 0])).toEqual({ from: 0, masses: [0] });
		expect(band([])).toEqual({ from: 0, masses: [0] });
	});
});

describe('ticks', () => {
	it('steps in fives when the tallest column is small', () => {
		expect(ticks(0.12)).toEqual([0, 0.05, 0.1, 0.15]);
	});

	it('opens the step up rather than crowding the axis', () => {
		expect(ticks(0.9)).toEqual([0, 0.25, 0.5, 0.75, 1]);
	});

	it('always reaches past the tallest column', () => {
		for (const max of [0.01, 0.33, 0.67, 1]) {
			const scale = ticks(max);
			expect(scale[scale.length - 1]).toBeGreaterThanOrEqual(max);
			expect(scale[0]).toBe(0);
		}
	});
});

describe('percent', () => {
	it('gives a place to small probabilities and none to large', () => {
		expect(percent(0.925)).toBe('93%');
		expect(percent(0.013)).toBe('1.3%');
	});

	it('does not round a real chance to nothing, or a partial one to all', () => {
		expect(percent(0.0004)).toBe('<0.1%');
		expect(percent(0.999)).toBe('>99%');
		expect(percent(0)).toBe('0%');
		expect(percent(1)).toBe('100%');
	});
});

describe('percents', () => {
	it('prints chances making up a whole so they add up to 100%', () => {
		const taken = 0.81522;
		const given = [0.23291, 0.35586, 0.22645].map((p) => p / taken);

		expect(given.map(percent)).toEqual(['29%', '44%', '28%']);
		expect(percents(given)).toEqual(['28%', '44%', '28%']);
	});

	it('prints them all to a place when one is small', () => {
		expect(percents([0.702, 0.0613, 0.0978, 0.1389])).toEqual(['70.2%', '6.1%', '9.8%', '13.9%']);
	});

	it('adds them up to their own sum when they make up part of a whole', () => {
		expect(percents([0.126, 0.126, 0.126])).toEqual(['13%', '13%', '12%']);
	});

	it('does not round a real chance to nothing, or a partial one to all', () => {
		expect(percents([0.6, 0.4, 0])).toEqual(['60%', '40%', '0%']);
		expect(percents([0.9996, 0.0002, 0.0002])).toEqual(['>99.9%', '<0.1%', '<0.1%']);
	});
});

describe('labelEvery', () => {
	it('labels every column when there is room', () => {
		expect(labelEvery(10, 400)).toBe(1);
	});

	it('thins the labels rather than letting them collide', () => {
		expect(labelEvery(30, 450)).toBe(2);
		expect(labelEvery(60, 300)).toBeGreaterThan(2);
	});
});
