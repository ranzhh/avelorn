import { describe, expect, it } from 'vitest';

import { clamped, closed, moved, opened, raised, spot, type Pane } from './panes';

const SIZE = { width: 320, height: 400 };
const SCREEN = { width: 1600, height: 900 };

const pane = (id: number, slug: string, x = 0, y = 0): Pane => ({
	id,
	subject: 'unit',
	slug,
	title: slug,
	x,
	y
});

describe('clamped', () => {
	it('pulls a pane dragged past the right edge back into the window', () => {
		expect(clamped(1500, 100, SIZE, SCREEN).x).toBe(1280);
	});

	it('leaves a grip on screen when a pane is dragged off the left', () => {
		expect(clamped(-1000, 100, SIZE, SCREEN).x).toBe(40 - SIZE.width);
	});

	it('never lets a pane sit above the top, where its bar cannot be reached', () => {
		expect(clamped(100, -300, SIZE, SCREEN).y).toBe(0);
	});

	it('keeps a pane taller than the window at the top rather than pushing it up', () => {
		expect(clamped(100, 50, { width: 320, height: 1200 }, SCREEN).y).toBe(0);
	});
});

describe('spot', () => {
	it('cascades a pane off the one it was opened from', () => {
		const parent = pane(1, 'elven-spearmen', 400, 200);
		expect(spot([parent], SIZE, SCREEN, parent)).toEqual({ x: 424, y: 224 });
	});

	it('steps successive cold opens apart so one never hides another', () => {
		const first = spot([], SIZE, SCREEN);
		const second = spot([pane(1, 'a')], SIZE, SCREEN);
		expect(second.x).toBeGreaterThan(first.x);
		expect(second.y).toBeGreaterThan(first.y);
	});

	it('lands a cascade inside the window when its parent is against the edge', () => {
		const parent = pane(1, 'a', 1280, 860);
		expect(spot([parent], SIZE, SCREEN, parent)).toEqual({ x: 1280, y: 500 });
	});
});

describe('opened', () => {
	it('raises the pane already reading an entry rather than opening a second', () => {
		const open = [pane(1, 'charge'), pane(2, 'elven-spearmen')];
		const again = opened(
			open,
			{ id: 9, subject: 'unit', slug: 'charge', title: 'Charge' },
			SIZE,
			SCREEN
		);
		expect(again.map((each) => each.id)).toEqual([2, 1]);
	});

	it('tells a rule from a datasheet filed under the same slug', () => {
		const open = [pane(1, 'great-eagle')];
		const both = opened(
			open,
			{ id: 2, subject: 'rule', slug: 'great-eagle', title: 'Great Eagle' },
			SIZE,
			SCREEN
		);
		expect(both).toHaveLength(2);
	});
});

describe('raised', () => {
	it('puts the raised pane last, which is the top of the stack', () => {
		const open = [pane(1, 'a'), pane(2, 'b'), pane(3, 'c')];
		expect(raised(open, 1).map((each) => each.id)).toEqual([2, 3, 1]);
	});

	it('leaves the list alone when the pane is already on top', () => {
		const open = [pane(1, 'a'), pane(2, 'b')];
		expect(raised(open, 2)).toBe(open);
	});
});

describe('moved', () => {
	it('clamps the corner it is dropped at', () => {
		const open = [pane(1, 'a', 100, 100)];
		expect(moved(open, 1, 5000, 100, SIZE, SCREEN)[0].x).toBe(1280);
	});

	it('leaves every other pane where it was', () => {
		const open = [pane(1, 'a', 100, 100), pane(2, 'b', 200, 200)];
		expect(moved(open, 1, 300, 300, SIZE, SCREEN)[1]).toEqual(open[1]);
	});
});

describe('closed', () => {
	it('drops one pane and keeps the order of the rest', () => {
		const open = [pane(1, 'a'), pane(2, 'b'), pane(3, 'c')];
		expect(closed(open, 2).map((each) => each.id)).toEqual([1, 3]);
	});
});
