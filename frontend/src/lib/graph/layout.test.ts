import { describe, expect, it } from 'vitest';

import { LEAST, METRICS, caption, expected, fitted, layout, moved, type Box } from './layout';
import type { Point } from './layout';
import type { Distribution, Program, Reading, Roll } from './types';

const program: Program = {
	program: 'p',
	sides: { 'this-model': 'one', 'the-enemy': 'two' },
	nodes: [
		{
			path: 'p/a',
			step: 'a',
			kind: 'measurement',
			side: 'this-model',
			inputs: [],
			edge: { readings: [{ label: 'n', value: 2 }] }
		},
		{
			path: 'p/g/b',
			step: 'b',
			kind: 'roll',
			side: 'this-model',
			inputs: [],
			target: { label: 't', value: 1 },
			modifiers: [{ rule: 'r1', move: 1 }],
			edge: {
				readings: [
					{
						label: 'x',
						outcomes: [
							{ value: 0, p: 0.5 },
							{ value: 2, p: 0.5 }
						]
					}
				]
			}
		},
		{
			path: 'p/g/c',
			step: 'c',
			kind: 'roll',
			side: 'the-enemy',
			inputs: ['p/g/b'],
			target: {
				label: 'u',
				outcomes: [
					{ value: 1, p: 0.75 },
					{ value: 2, p: 0.25 }
				]
			},
			modifiers: [],
			edge: {
				readings: [
					{
						label: 'y',
						outcomes: [
							{ value: 0, p: 0.25 },
							{ value: 1, p: 0.5 },
							{ value: 2, p: 0.25 }
						]
					}
				]
			}
		},
		{
			path: 'p/d',
			step: 'd',
			kind: 'consequence',
			side: 'the-enemy',
			inputs: ['p/g/c'],
			edge: {
				readings: [
					{
						label: 'z',
						outcomes: [
							{ value: 'p', p: 0.5 },
							{ value: 'q', p: 0.5 }
						]
					}
				]
			}
		}
	],
	blocks: [{ path: 'p/g', kind: 'repeat', times: 'p/a', collapsed: false }],
	rules: [
		{
			rule: 'r1',
			name: 'R1',
			bearer: 'this-model',
			landings: [{ at: 'p/g/b', verdict: 'applied' }]
		},
		{ rule: 'r2', name: 'R2', bearer: 'core', landings: [] }
	],
	lanes: []
};

const GROUP = 'p/g';
const paths = program.nodes.map((node) => node.path);
const children = paths.filter((path) => path.startsWith(`${GROUP}/`));

const expanded = layout(program, []);
const collapsed = layout(program, [GROUP]);

const isDistribution = (reading: Reading): reading is Distribution => 'outcomes' in reading;
const rolls = program.nodes.filter((node): node is Roll => node.kind === 'roll');

function inside(inner: Box, outer: Box): boolean {
	return (
		inner.x >= outer.x &&
		inner.y >= outer.y &&
		inner.x + inner.width <= outer.x + outer.width &&
		inner.y + inner.height <= outer.y + outer.height
	);
}

function onBoundary(point: Point, box: Box): boolean {
	const onX = point.x >= box.x && point.x <= box.x + box.width;
	const onY = point.y >= box.y && point.y <= box.y + box.height;
	const atEdge =
		point.x === box.x ||
		point.x === box.x + box.width ||
		point.y === box.y ||
		point.y === box.y + box.height;
	return onX && onY && atEdge;
}

describe('the program the tests draw', () => {
	it('gives every node its own path', () => {
		expect(new Set(paths).size).toBe(paths.length);
	});

	it('reads only from nodes that exist', () => {
		for (const node of program.nodes) {
			for (const input of node.inputs) expect(paths).toContain(input);
		}
	});

	it('lands every rule on a node that exists', () => {
		for (const rule of program.rules) {
			for (const landing of rule.landings) expect(paths).toContain(landing.at);
		}
	});

	it('puts every block around at least one node and multiplies it by an edge that exists', () => {
		for (const block of program.blocks) {
			expect(paths.some((path) => path.startsWith(`${block.path}/`))).toBe(true);
			if (block.kind === 'repeat') expect(paths).toContain(block.times);
		}
	});

	it('gives every distribution a total mass of one', () => {
		const distributions = [
			...program.nodes.flatMap((node) => node.edge.readings),
			...rolls.map((roll) => roll.target)
		].filter(isDistribution);
		expect(distributions.length).toBeGreaterThan(0);
		for (const distribution of distributions) {
			const total = distribution.outcomes.reduce((sum, outcome) => sum + outcome.p, 0);
			expect(Math.abs(total - 1)).toBeLessThan(1e-9);
		}
	});

	it('names an applied rule behind every modifier', () => {
		for (const roll of rolls) {
			for (const modifier of roll.modifiers) {
				const rule = program.rules.find((candidate) => candidate.rule === modifier.rule);
				expect(rule?.landings).toContainEqual({ at: roll.path, verdict: 'applied' });
			}
		}
	});
});

describe('layout', () => {
	it('places the steps in program order, left to right', () => {
		expect(expanded.steps.map((step) => step.path)).toEqual(paths);
		const xs = expanded.steps.map((step) => step.box.x);
		expect([...xs].sort((a, b) => a - b)).toEqual(xs);
		expect(new Set(xs).size).toBe(xs.length);
	});

	it('draws the group as a box around its own steps and nothing else', () => {
		const frame = expanded.blocks.find((block) => block.path === GROUP)!;
		expect(frame.collapsed).toBe(false);
		for (const step of expanded.steps) {
			expect(inside(step.box, frame.box)).toBe(children.includes(step.path));
		}
	});

	it('labels the group with the reading of its times edge', () => {
		const frame = expanded.blocks.find((block) => block.path === GROUP)!;
		expect(frame.multiplier).toEqual([{ label: 'n', value: 2 }]);
	});

	it('joins consecutive steps by their inputs and carries the source edge', () => {
		const joined = expanded.edges
			.filter((edge) => edge.kind === 'input')
			.map((edge) => [edge.from, edge.to]);
		expect(joined).toEqual(
			program.nodes.flatMap((node) => node.inputs.map((input) => [input, node.path]))
		);
		const intoC = expanded.edges.find((edge) => edge.to === 'p/g/c')!;
		expect(intoC.readings[0].label).toBe('x');
	});

	it('runs the multiplier into the group and the last step out of the program', () => {
		expect(expanded.edges).toContainEqual(
			expect.objectContaining({ kind: 'times', from: 'p/a', to: GROUP })
		);
		expect(expanded.edges).toContainEqual(
			expect.objectContaining({ kind: 'output', from: 'p/d', to: null })
		);
	});

	it('starts and ends every edge on a drawn box', () => {
		const boxes = [...expanded.steps.map((s) => s.box), ...expanded.blocks.map((b) => b.box)];
		for (const edge of expanded.edges) {
			expect(boxes.some((box) => onBoundary(edge.start, box))).toBe(true);
			if (edge.to) expect(boxes.some((box) => onBoundary(edge.end, box))).toBe(true);
		}
	});

	it('collapses the group to one node, dropping its children', () => {
		const shown = collapsed.steps.map((step) => step.path);
		for (const child of children) expect(shown).not.toContain(child);
		const node = collapsed.blocks.find((block) => block.path === GROUP)!;
		expect(node.collapsed).toBe(true);
		expect(node.box.width).toBe(expanded.steps[0].box.width);
		expect(node.summary).toBe('x 0–2 · y 0–2');
		expect(collapsed.width).toBeLessThan(expanded.width);
	});

	it('collapses an ordinary semantic sequence as well as a repeat', () => {
		const semantic = {
			...program,
			blocks: [{ path: GROUP, kind: 'sequence' as const, collapsed: false }]
		};
		const drawn = layout(semantic, [GROUP]);
		expect(drawn.steps.map((step) => step.path)).not.toContain('p/g/b');
		expect(drawn.blocks.find((block) => block.path === GROUP)?.summary).toBe('x 0–2 · y 0–2');
	});

	it('keeps the edges into and out of the collapsed group', () => {
		expect(collapsed.edges.map((edge) => [edge.kind, edge.from, edge.to])).toEqual([
			['input', GROUP, 'p/d'],
			['times', 'p/a', GROUP],
			['output', 'p/d', null]
		]);
		const out = collapsed.edges.find((edge) => edge.from === GROUP)!;
		expect(out.readings[0].label).toBe('y');
	});

	it('lands every rule line on a drawn node, expanded or collapsed', () => {
		for (const drawn of [expanded, collapsed]) {
			expect(drawn.landings.length).toBe(1);
			const boxes = [...drawn.steps.map((s) => s.box), ...drawn.blocks.map((b) => b.box)];
			for (const landing of drawn.landings) {
				expect(boxes.some((box) => onBoundary(landing.end, box))).toBe(true);
				expect(drawn.rail.some((placed) => onBoundary(landing.start, placed.box))).toBe(true);
			}
		}
		expect(expanded.landings[0].at).toBe('p/g/b');
		expect(collapsed.landings[0].at).toBe(GROUP);
	});

	it('sets a rule with no landing aside as not modelled', () => {
		expect(expanded.unmodelled.map((rule) => rule.rule)).toEqual(['r2']);
		expect(expanded.rail.map((placed) => placed.rule.rule)).toEqual(['r1']);
	});

	it('fits the flow into a narrower width and no narrower than the floor', () => {
		expect(fitted(program, [], 2000)).toEqual(METRICS);
		const snug = fitted(program, [], 700);
		expect(snug).not.toEqual(METRICS);
		expect(layout(program, [], snug).width).toBeLessThanOrEqual(700);
		expect(snug.node.width).toBeGreaterThanOrEqual(LEAST.node.width);
		expect(snug.gap).toBeGreaterThanOrEqual(LEAST.gap);
		expect(fitted(program, [], 100)).toEqual(LEAST);
	});
});

describe('moving what was laid out', () => {
	const step = 'p/d';

	it('moves one step and re-aims the edges into and out of it', () => {
		const shifted = moved(expanded, { [step]: { x: 40, y: -30 } });
		const before = expanded.steps.find((each) => each.path === step)!.box;
		const after = shifted.steps.find((each) => each.path === step)!.box;
		expect(after).toEqual({ ...before, x: before.x + 40, y: before.y - 30 });
		const into = shifted.edges.find((edge) => edge.to === step)!;
		expect(into.end).toEqual({ x: after.x, y: after.y + after.height / 2 });
		const out = shifted.edges.find((edge) => edge.from === step)!;
		expect(out.start).toEqual({ x: after.x + after.width, y: after.y + after.height / 2 });
		for (const other of shifted.steps.filter((each) => each.path !== step)) {
			expect(other.box).toEqual(expanded.steps.find((each) => each.path === other.path)!.box);
		}
	});

	it('moves a group frame together with every step inside it', () => {
		const shifted = moved(expanded, { [GROUP]: { x: -25, y: 60 } });
		const frame = shifted.blocks.find((block) => block.path === GROUP)!;
		const was = expanded.blocks.find((block) => block.path === GROUP)!.box;
		expect(frame.box).toEqual({ ...was, x: was.x - 25, y: was.y + 60 });
		for (const path of children) {
			const before = expanded.steps.find((each) => each.path === path)!.box;
			const after = shifted.steps.find((each) => each.path === path)!.box;
			expect(after).toEqual({ ...before, x: before.x - 25, y: before.y + 60 });
			expect(inside(after, frame.box)).toBe(true);
		}
		const outside = shifted.steps.find((each) => each.path === 'p/a')!;
		expect(outside.box).toEqual(expanded.steps[0].box);
	});

	it("adds a step's own move to the move of the frame carrying it", () => {
		const shifted = moved(expanded, {
			[GROUP]: { x: 10, y: 10 },
			'p/g/b': { x: 5, y: -5 }
		});
		const before = expanded.steps.find((each) => each.path === 'p/g/b')!.box;
		const after = shifted.steps.find((each) => each.path === 'p/g/b')!.box;
		expect(after).toEqual({ ...before, x: before.x + 15, y: before.y + 5 });
	});

	it('grows the frame around a child dragged past its edge, never letting it out', () => {
		const frame = expanded.blocks.find((block) => block.path === GROUP)!.box;
		const child = 'p/g/c';
		const far = { x: frame.width, y: -3 * frame.height };
		const shifted = moved(expanded, { [child]: far });
		const after = shifted.blocks.find((block) => block.path === GROUP)!.box;
		const box = shifted.steps.find((each) => each.path === child)!.box;
		expect(inside(box, after)).toBe(true);
		expect(after.width).toBeGreaterThan(frame.width);
		expect(after.y).toBeLessThan(frame.y);
		for (const path of children.filter((each) => each !== child)) {
			expect(inside(shifted.steps.find((each) => each.path === path)!.box, after)).toBe(true);
		}
		const into = shifted.edges.find((edge) => edge.kind === 'times')!;
		expect(into.end).toEqual({ x: after.x, y: after.y + after.height / 2 });
		expect(shifted.width).toBeGreaterThanOrEqual(after.x + after.width);
		expect(shifted.height).toBeGreaterThanOrEqual(after.y + after.height);
	});

	it('keeps every landing line pinned to its rule card and its step after moves', () => {
		const shifted = moved(expanded, {
			'p/g/b': { x: 30, y: 0 },
			r1: { x: 0, y: 20 }
		});
		const card = shifted.rail.find((placed) => placed.rule.rule === 'r1')!.box;
		expect(card.y).toBe(expanded.rail[0].box.y + 20);
		const landing = shifted.landings.find((each) => each.rule === 'r1')!;
		expect(landing.start).toEqual({ x: card.x + card.width / 2, y: card.y });
		const target = shifted.steps.find((each) => each.path === landing.at)!.box;
		expect(landing.end).toEqual({ x: target.x + target.width / 2, y: target.y + target.height });
	});
});

describe('captions', () => {
	const x = program.nodes[1].edge.readings[0] as Distribution;
	const z = program.nodes[3].edge.readings[0] as Distribution;

	it('takes the expected value of a numeric distribution and none of a named one', () => {
		expect(expected(x)).toBe(1);
		expect(expected(z)).toBeNull();
	});

	it('captions an edge with its first reading, one line', () => {
		expect(caption(program.nodes[0].edge.readings)).toBe('n 2');
		expect(caption([x])).toBe('x · 1.0');
		expect(caption([z])).toBe('z');
		expect(caption([])).toBe('');
	});
});
