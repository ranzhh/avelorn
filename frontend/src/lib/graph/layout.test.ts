import { describe, expect, it } from 'vitest';

import {
	CAPTION,
	FRAME,
	LANE,
	LEAST,
	METRICS,
	caption,
	expected,
	fitted,
	foldable,
	landed,
	layout,
	moved,
	startsFolded,
	type Box
} from './layout';
import type { Point } from './layout';
import type { Block, Distribution, Judged, Node, Program, Reading, Roll } from './types';

const program: Program = {
	program: 'p',
	sides: ['one', 'two'],
	nodes: [
		{
			path: 'p/a',
			step: 'a',
			kind: 'measurement',
			side: 'one',
			ran: true,
			inputs: [],
			edge: { readings: [{ label: 'n', value: 2 }] },
			changes: []
		},
		{
			path: 'p/g/b',
			step: 'b',
			kind: 'roll',
			side: 'one',
			ran: true,
			inputs: [],
			target: { label: 't', value: 1 },
			printed: { label: 't', value: 2 },
			changes: [{ rule: 'one/p/r1', text: '+1' }],
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
			side: 'two',
			ran: true,
			inputs: ['p/g/b'],
			target: {
				label: 'u',
				outcomes: [
					{ value: 1, p: 0.75 },
					{ value: 2, p: 0.25 }
				]
			},
			printed: null,
			changes: [],
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
			side: 'two',
			ran: true,
			inputs: ['p/g/c'],
			changes: [],
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
			id: 'one/p/r1',
			rule: 'r1',
			name: 'R1',
			holder: { side: 'one', part: 'p' },
			may: false,
			sources: [{ carrier: 'effect', item: null, profile: null, via: 'one/p/r3' }],
			landings: [{ at: 'p/g/b', triggers: ['p/a'], verdicts: [{ verdict: 'applied', p: 1 }] }]
		},
		{
			id: 'two/q/r2',
			rule: 'r2',
			name: 'R2',
			holder: { side: 'two', part: 'q' },
			may: false,
			sources: [{ carrier: 'effect', item: null, profile: null, via: 'two/q/r4' }],
			landings: []
		},
		{
			id: 'one/p/r3',
			rule: 'r3',
			name: 'R3',
			holder: { side: 'one', part: 'p' },
			may: false,
			sources: [{ carrier: 'model', item: null, profile: null, via: null }],
			landings: []
		},
		{
			id: 'two/q/r4',
			rule: 'r4',
			name: 'R4',
			holder: { side: 'two', part: 'q' },
			may: false,
			sources: [{ carrier: 'core', item: null, profile: null, via: null }],
			landings: []
		}
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
			...program.nodes.filter((node) => node.ran).flatMap((node) => node.edge.readings),
			...rolls.filter((roll) => roll.ran).map((roll) => roll.target)
		].filter(isDistribution);
		expect(distributions.length).toBeGreaterThan(0);
		for (const distribution of distributions) {
			const total = distribution.outcomes.reduce((sum, outcome) => sum + outcome.p, 0);
			expect(Math.abs(total - 1)).toBeLessThan(1e-9);
		}
	});

	it('lands the rule behind every change on its step', () => {
		for (const node of program.nodes) {
			for (const change of node.changes) {
				const rule = program.rules.find((candidate) => candidate.id === change.rule);
				expect(rule?.landings).toContainEqual(expect.objectContaining({ at: node.path }));
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
		expect(node.summary).toEqual([
			{ side: 'one', text: 'x · 1.0', every: 'x · 1.0' },
			{ side: 'two', text: 'y · 1.0', every: 'y · 1.0' }
		]);
		expect(collapsed.width).toBeLessThan(expanded.width);
	});

	it('collapses an ordinary semantic sequence as well as a repeat', () => {
		const semantic = {
			...program,
			blocks: [{ path: GROUP, kind: 'sequence' as const, collapsed: false }]
		};
		const drawn = layout(semantic, [GROUP]);
		expect(drawn.steps.map((step) => step.path)).not.toContain('p/g/b');
		expect(drawn.blocks.find((block) => block.path === GROUP)?.summary).toEqual([
			{ side: 'one', text: 'x · 1.0', every: 'x · 1.0' },
			{ side: 'two', text: 'y · 1.0', every: 'y · 1.0' }
		]);
	});

	it('sums up a folded group by the reading each side ends on, keeping every reading', () => {
		const onSide = (side: string) => ({
			...program,
			nodes: program.nodes.map((node) => (node.path === 'p/g/c' ? { ...node, side } : node))
		});
		const summed = (side: string) =>
			layout(onSide(side), [GROUP]).blocks.find((block) => block.path === GROUP)!.summary;
		expect(summed('two').map((line) => [line.side, line.text])).toEqual([
			['one', 'x · 1.0'],
			['two', 'y · 1.0']
		]);
		expect(summed('one')).toEqual([{ side: 'one', text: 'y · 1.0', every: 'x · 1.0, y · 1.0' }]);
	});

	it('starts a slot folded and a sequence or repeat as its program prints it', () => {
		const blocks: Block[] = [
			{ path: 'p/s', kind: 'slot', empty: false },
			{ path: 'p/q', kind: 'sequence', collapsed: false },
			{ path: 'p/r', kind: 'repeat', times: 'p/a', collapsed: true },
			{ path: 'p/b', kind: 'body', decision: 'p/a' }
		];
		expect(blocks.map(startsFolded)).toEqual([true, false, true, false]);
		expect(blocks.map(foldable)).toEqual([true, true, true, false]);
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

	it('sets aside as not modelled every rule that reaches no landing', () => {
		expect(expanded.unmodelled.map((rule) => rule.id)).toEqual(['two/q/r2', 'two/q/r4']);
	});

	it('squeezes the flow to fit, and keeps it full size when even the floor overflows', () => {
		const widest = layout(program, [], METRICS).width;
		const narrowest = layout(program, [], LEAST).width;
		expect(fitted(program, [], widest)).toEqual(METRICS);
		for (const available of [narrowest, (narrowest + widest) / 2, widest - 1]) {
			const snug = fitted(program, [], available);
			expect(snug).not.toEqual(METRICS);
			expect(layout(program, [], snug).width).toBeLessThanOrEqual(available);
			expect(snug.node.width).toBeGreaterThanOrEqual(LEAST.node.width);
			expect(snug.gap).toBeGreaterThanOrEqual(LEAST.gap);
		}
		expect(fitted(program, [], narrowest - 1)).toEqual(METRICS);
	});
});

const measured = (path: string, side: string, inputs: string[] = []): Node => ({
	path,
	step: path.slice(path.lastIndexOf('/') + 1),
	kind: 'measurement',
	side,
	ran: true,
	inputs,
	edge: { readings: [{ label: 'v', value: 1 }] },
	changes: []
});

const fought: Program = {
	program: 'r',
	sides: ['one', 'two'],
	nodes: [
		measured('r/two/ready', 'two'),
		measured('r/one/ready', 'one'),
		measured('r/one/count', 'one', ['r/one/ready']),
		measured('r/one/attack/champion/hit', 'one'),
		measured('r/one/attack/champion/wound', 'one', ['r/one/attack/champion/hit']),
		measured('r/one/attack/ranks/hit', 'one'),
		measured('r/one/attack/ranks/wound', 'one', ['r/one/attack/ranks/hit']),
		measured('r/slot-2/one/strike', 'one', ['r/two/ready']),
		measured('r/slot-1/one/strike', 'one', ['r/one/ready'])
	],
	blocks: [
		{ path: 'r/one/attack', kind: 'sequence', collapsed: false },
		{ path: 'r/one/attack/champion', kind: 'repeat', times: 'r/one/count', collapsed: false },
		{ path: 'r/one/attack/ranks', kind: 'repeat', times: 'r/one/count', collapsed: false }
	],
	rules: [],
	lanes: []
};

describe('columns', () => {
	const drawn = layout(fought, []);
	const box = (path: string) => drawn.steps.find((step) => step.path === path)!.box;
	const frame = (path: string) => drawn.blocks.find((block) => block.path === path)!.box;
	const above = (upper: Box, lower: Box) => upper.y + upper.height < lower.y;

	it('stacks the group each part attacks in, step by step', () => {
		for (const step of ['hit', 'wound']) {
			expect(box(`r/one/attack/ranks/${step}`).x).toBe(box(`r/one/attack/champion/${step}`).x);
		}
		expect(above(frame('r/one/attack/champion'), frame('r/one/attack/ranks'))).toBe(true);
	});

	it('moves one column right for each step that follows another', () => {
		const xs = [
			'r/two/ready',
			'r/one/ready',
			'r/one/count',
			'r/one/attack/champion/hit',
			'r/one/attack/champion/wound',
			'r/slot-2/one/strike',
			'r/slot-1/one/strike'
		].map((path) => box(path).x);
		xs.slice(1).forEach((x, index) => expect(x).toBeGreaterThan(xs[index] + METRICS.node.width));
		expect(new Set(drawn.steps.map((step) => step.box.x))).toEqual(new Set(xs));
	});

	it('adds up what the parts of a folded group end on side by side', () => {
		const wounds = (mean: number): Reading => ({
			label: 'wounds',
			outcomes: [
				{ value: 0, p: 1 - mean / 2 },
				{ value: 2, p: mean / 2 }
			]
		});
		const rolled = {
			...fought,
			nodes: fought.nodes.map((node) =>
				node.step === 'wound'
					? { ...node, edge: { readings: [wounds(node.path.includes('champion') ? 0.5 : 1.5)] } }
					: node
			)
		};
		const card = layout(rolled, ['r/one/attack']).blocks.find(
			(block) => block.path === 'r/one/attack'
		)!;
		expect(card.summary.map((line) => [line.side, line.text])).toEqual([['one', 'wounds · 2.0']]);
	});

	it('carries a read past columns on a lane clear of their cards, and ends no output on one', () => {
		const along = (a: Point, b: Point) =>
			Array.from({ length: 19 }, (_, index) => ({
				x: a.x + ((b.x - a.x) * (index + 1)) / 20,
				y: a.y + ((b.y - a.y) * (index + 1)) / 20
			}));
		const covers = (box: Box, point: Point) =>
			point.x > box.x &&
			point.x < box.x + box.width &&
			point.y > box.y &&
			point.y < box.y + box.height;
		for (const each of [drawn, layout(fought, ['r/one/attack'])]) {
			const cards = [...each.steps, ...each.blocks.filter((block) => block.collapsed)];
			for (const edge of each.edges) {
				const route = [edge.start, ...edge.via, edge.end];
				const points = route.slice(1).flatMap((point, index) => along(route[index], point));
				for (const { box } of cards) {
					const beside = { ...box, x: box.x - LANE.step, width: box.width + 2 * LANE.step };
					expect(points.some((point) => covers(box, point))).toBe(false);
					expect(edge.via.some((corner) => covers(beside, corner))).toBe(false);
				}
				if (!edge.to) expect(cards.some((card) => onBoundary(edge.end, card.box))).toBe(false);
			}
		}
		const sent = drawn.edges.filter((edge) => edge.from === 'r/two/ready');
		expect(sent.map((edge) => [edge.kind, edge.to])).toEqual([['input', 'r/slot-2/one/strike']]);
		const reader = box('r/slot-2/one/strike');
		expect(sent[0].end).toEqual({ x: reader.x, y: reader.y + reader.height / 2 });
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
		expect(after.height).toBeGreaterThan(frame.height);
		for (const path of children.filter((each) => each !== child)) {
			expect(inside(shifted.steps.find((each) => each.path === path)!.box, after)).toBe(true);
		}
		const into = shifted.edges.find((edge) => edge.kind === 'times')!;
		expect(into.end).toEqual({ x: after.x, y: after.y + (after.height + FRAME.header) / 2 });
		expect(shifted.width).toBeGreaterThanOrEqual(after.x + after.width);
		expect(shifted.height).toBeGreaterThanOrEqual(after.y + after.height);
	});

	it('keeps a step dragged off the top left on the canvas, carrying the rest with it', () => {
		const shifted = moved(expanded, { 'p/g/c': { x: -400, y: -400 } });
		const boxes = [
			...shifted.steps.map((each) => each.box),
			...shifted.blocks.map((each) => each.box)
		];
		for (const box of boxes) {
			expect(box.x).toBeGreaterThanOrEqual(0);
			expect(box.y).toBeGreaterThanOrEqual(0);
			expect(box.x + box.width).toBeLessThanOrEqual(shifted.width);
			expect(box.y + box.height).toBeLessThanOrEqual(shifted.height);
		}
		for (const point of shifted.edges.flatMap((edge) => [edge.start, edge.end])) {
			expect(point.x).toBeGreaterThanOrEqual(0);
			expect(point.y).toBeGreaterThanOrEqual(0);
		}
		const dragged = shifted.steps.find((each) => each.path === 'p/g/c')!.box;
		const still = shifted.steps.find((each) => each.path === 'p/a')!.box;
		const was = expanded.steps.find((each) => each.path === 'p/a')!.box;
		expect(still.x - dragged.x).toBe(
			was.x - expanded.steps.find((e) => e.path === 'p/g/c')!.box.x + 400
		);
		expect(still.y).toBeGreaterThan(was.y);
	});
});

describe('the rules a step lists', () => {
	it('lists every rule that lands on the step, ticked only where it applied', () => {
		const judged = (verdicts: Judged[]) => ({
			...program,
			rules: [
				...program.rules,
				{
					...program.rules[1],
					id: 'two/q/r5',
					landings: [{ at: 'p/g/b', triggers: [], verdicts }]
				}
			]
		});
		const listed = (verdicts: Judged[]) =>
			landed(judged(verdicts), 'p/g/b').map((each) => [each.rule.id, each.applied]);
		expect(listed([{ verdict: 'honoured', p: 1 }])).toEqual([
			['one/p/r1', true],
			['two/q/r5', false]
		]);
		expect(
			listed([
				{ verdict: 'applied', p: 0.25 },
				{ verdict: 'held', p: 0.75 }
			])
		).toEqual([
			['one/p/r1', true],
			['two/q/r5', true]
		]);
		expect(listed([])).toEqual([
			['one/p/r1', true],
			['two/q/r5', false]
		]);
		expect(landed(program, 'p/d')).toEqual([]);
	});
});

describe('captions', () => {
	const x = program.nodes[1].edge.readings[0] as Distribution;
	const z = program.nodes[3].edge.readings[0] as Distribution;

	it('takes the expected value of a numeric distribution and none of a named one', () => {
		expect(expected(x)).toBe(1);
		expect(expected(z)).toBeNull();
	});

	it('captions what leaves a step once, beside it, however many edges it sends', () => {
		const drawn = layout(fought, []);
		const from = 'r/one/count';
		const count = drawn.steps.find((step) => step.path === from)!.box;
		expect(drawn.edges.filter((edge) => edge.from === from).map((edge) => edge.to)).toEqual([
			'r/one/attack/champion',
			'r/one/attack/ranks'
		]);
		expect(drawn.captions.filter((each) => each.from === from).map((each) => each.at)).toEqual([
			{ x: count.x + count.width + drawn.metrics.gap / 2, y: count.y + count.height / 2 }
		]);
	});

	it('holds every caption clear of the cards on either side of it, however squeezed', () => {
		const wordy = {
			...program,
			nodes: program.nodes.map((node) =>
				node.path === 'p/g/b'
					? {
							...node,
							edge: {
								readings: node.edge.readings.map((each) => ({ ...each, label: 'wounds-lost' }))
							}
						}
					: node
			)
		};
		for (const metrics of [METRICS, LEAST]) {
			const drawn = layout(wordy, [], metrics);
			expect(drawn.captions.map((each) => each.text)).toContain('wounds-lost · 1.0');
			for (const each of drawn.captions) {
				const half = (each.text.length * CAPTION.glyph) / 2 + CAPTION.pad;
				for (const { box } of drawn.steps) {
					expect(each.at.x + half <= box.x || each.at.x - half >= box.x + box.width).toBe(true);
				}
			}
		}
	});

	it('leaves what leaves a folded group to the summary on its card', () => {
		expect(collapsed.edges.some((edge) => edge.from === GROUP)).toBe(true);
		expect(collapsed.captions.map((each) => each.text)).toEqual(['n 2', 'z']);
		expect(expanded.captions.map((each) => each.text)).toEqual(['x · 1.0', 'y · 1.0', 'n 2', 'z']);
	});

	it('captions an edge with its first reading, one line', () => {
		expect(caption(program.nodes[0].edge.readings)).toBe('n 2');
		expect(caption([x])).toBe('x · 1.0');
		expect(caption([z])).toBe('z');
		expect(caption([])).toBe('');
	});
});
