import { describe, expect, it } from 'vitest';

import {
	MEASURE,
	clamped,
	closed,
	measure,
	moved,
	opened,
	raised,
	spot,
	topmost,
	type Pane,
	type Subject
} from './panes';

const SIZE = { width: 320, height: 400 };
const SCREEN = { width: 1600, height: 900 };

const pane = (id: number, slug: string, x = 0, y = 0): Pane => ({
	id,
	subject: 'unit',
	slug,
	title: slug,
	x,
	y,
	z: id
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

	it('steps past a corner a sibling already took', () => {
		const parent = pane(1, 'white-lions', 300, 72);
		const first = spot([parent], SIZE, SCREEN, parent);
		const child = { ...parent, id: 2, ...first };
		const second = spot([parent, child], SIZE, SCREEN, parent);
		expect(second).not.toEqual(first);
		expect(second.x).toBeGreaterThan(first.x);
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
		expect(again).toHaveLength(2);
		expect(topmost(again)?.id).toBe(1);
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

	it('gives two blocks of one datasheet a pane each', () => {
		const first = opened(
			[],
			{ id: 1, subject: 'unit', slug: 'white-lions', title: 'A · White Lions', block: 1 },
			SIZE,
			SCREEN
		);
		const both = opened(
			first,
			{ id: 2, subject: 'unit', slug: 'white-lions', title: 'B · White Lions', block: 2 },
			SIZE,
			SCREEN
		);
		expect(both).toHaveLength(2);
		expect(both.map((each) => each.block)).toEqual([1, 2]);
	});

	it("raises a block's own pane rather than opening it twice", () => {
		const open = opened(
			[],
			{ id: 1, subject: 'unit', slug: 'white-lions', title: 'A · White Lions', block: 1 },
			SIZE,
			SCREEN
		);
		const again = opened(
			open,
			{ id: 2, subject: 'unit', slug: 'white-lions', title: 'A · White Lions', block: 1 },
			SIZE,
			SCREEN
		);
		expect(again).toHaveLength(1);
		expect(again[0].id).toBe(1);
	});

	it("keeps a block's pane apart from the same datasheet read off the roster", () => {
		const open = opened(
			[],
			{ id: 1, subject: 'unit', slug: 'white-lions', title: 'White Lions' },
			SIZE,
			SCREEN
		);
		const both = opened(
			open,
			{ id: 2, subject: 'unit', slug: 'white-lions', title: 'A · White Lions', block: 1 },
			SIZE,
			SCREEN
		);
		expect(both).toHaveLength(2);
	});
});

describe('measure', () => {
	it("widens a block's pane by the aside it carries", () => {
		const bare = measure({ subject: 'unit' });
		const withOptions = measure({ subject: 'unit', block: 1 });
		expect(bare.width).toBe(MEASURE.unit.width);
		expect(withOptions.width).toBeGreaterThan(bare.width);
		expect(withOptions.height).toBe(bare.height);
	});
});

describe('raised', () => {
	it('puts the raised pane on top of the stack', () => {
		const open = [pane(1, 'a'), pane(2, 'b'), pane(3, 'c')];
		expect(topmost(raised(open, 1))?.id).toBe(1);
	});

	it('keeps the list in the order it opened in', () => {
		const open = [pane(1, 'a'), pane(2, 'b'), pane(3, 'c')];
		expect(raised(open, 1).map((each) => each.id)).toEqual([1, 2, 3]);
	});

	it('leaves the list alone when the pane is already on top', () => {
		const open = [pane(1, 'a'), pane(2, 'b')];
		expect(raised(open, 2)).toBe(open);
	});
});

describe('topmost', () => {
	it('reads the stack off the order, not off the list', () => {
		const open = [pane(1, 'a'), pane(2, 'b')];
		expect(topmost(open)?.id).toBe(2);
		expect(topmost(raised(open, 1))?.id).toBe(1);
	});

	it('has nothing to report with no pane open', () => {
		expect(topmost([])).toBeNull();
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

describe('subjects', () => {
	it('measures every kind a pane can read', () => {
		const kinds: Subject[] = ['unit', 'rule', 'weapon', 'armour'];
		for (const kind of kinds) {
			expect(MEASURE[kind].width).toBeGreaterThan(0);
			expect(MEASURE[kind].height).toBeGreaterThan(0);
		}
	});

	it('tells a weapon from the rule filed under the same slug', () => {
		const open = opened(
			[],
			{ id: 1, subject: 'weapon', slug: 'daiths-reaper', title: "Daith's Reaper" },
			MEASURE.weapon,
			SCREEN
		);
		const both = opened(
			open,
			{ id: 2, subject: 'rule', slug: 'daiths-reaper', title: "Daith's Reaper" },
			MEASURE.rule,
			SCREEN
		);
		expect(both).toHaveLength(2);
		expect(both.map((each) => each.subject)).toEqual(['weapon', 'rule']);
	});

	it('cascades a three-deep chain down and right of each parent', () => {
		const sheet = pane(1, 'white-lions', 300, 72);
		const weapon = spot([sheet], MEASURE.weapon, SCREEN, sheet);
		const rule = spot([sheet, { ...sheet, id: 2, ...weapon }], MEASURE.rule, SCREEN, {
			...sheet,
			id: 2,
			...weapon
		});
		expect(weapon.x).toBeGreaterThan(sheet.x);
		expect(rule.x).toBeGreaterThan(weapon.x);
		expect(rule.y).toBeGreaterThan(weapon.y);
	});
});
