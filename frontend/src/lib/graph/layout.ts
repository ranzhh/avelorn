import type { Block, Distribution, Group, Node, Program, Reading, Rule, Verdict } from './types';

export interface Metrics {
	node: { width: number; height: number };
	gap: number;
}

export const METRICS: Metrics = { node: { width: 168, height: 72 }, gap: 64 };
export const LEAST: Metrics = { node: { width: 88, height: 72 }, gap: 32 };
export const FRAME = { pad: 12, header: 24 } as const;
export const RULE = { height: 40, gap: 16 } as const;
export const RAIL_GAP = 72;
export const MARGIN = 12;

export interface Point {
	x: number;
	y: number;
}

export interface Box {
	x: number;
	y: number;
	width: number;
	height: number;
}

export interface PlacedStep {
	path: string;
	node: Node;
	box: Box;
}

export interface PlacedBlock {
	path: string;
	block: Block;
	box: Box;
	collapsed: boolean;
	multiplier: Reading[];
	steps: string[];
}

export type EdgeKind = 'input' | 'times' | 'output';

export interface PlacedEdge {
	kind: EdgeKind;
	from: string;
	to: string | null;
	readings: Reading[];
	start: Point;
	end: Point;
}

export interface PlacedRule {
	rule: Rule;
	box: Box;
}

export interface PlacedLanding {
	rule: string;
	at: string;
	verdict: Verdict;
	start: Point;
	end: Point;
}

export interface Layout {
	metrics: Metrics;
	width: number;
	height: number;
	steps: PlacedStep[];
	blocks: PlacedBlock[];
	edges: PlacedEdge[];
	rail: PlacedRule[];
	landings: PlacedLanding[];
	unmodelled: Rule[];
}

export type Moves = Record<string, Point>;

type Item = { kind: 'step'; node: Node } | { kind: 'block'; block: Block; items: Item[] };

function enclosing(path: string, blocks: Block[]): Block | undefined {
	return blocks
		.filter((block) => path.startsWith(`${block.path}/`))
		.sort((a, b) => b.path.length - a.path.length)[0];
}

function firstStep(item: Item): string {
	return item.kind === 'step' ? item.node.path : firstStep(item.items[0]);
}

function tree(program: Program, parent: Block | undefined): Item[] {
	const order = new Map(program.nodes.map((node, index) => [node.path, index]));
	const under = (path: string) => enclosing(path, program.blocks)?.path === parent?.path;
	const steps: Item[] = program.nodes
		.filter((node) => under(node.path))
		.map((node) => ({ kind: 'step', node }));
	const blocks: Item[] = program.blocks
		.filter((block) => under(block.path))
		.map((block) => ({ kind: 'block', block, items: tree(program, block) }));
	return [...steps, ...blocks]
		.filter((item) => item.kind === 'step' || item.items.length > 0)
		.sort((a, b) => order.get(firstStep(a))! - order.get(firstStep(b))!);
}

function depth(items: Item[]): number {
	return Math.max(0, ...items.map((item) => (item.kind === 'block' ? 1 + depth(item.items) : 0)));
}

function isGroup(block: Block): block is Group {
	return block.kind === 'group';
}

function multiplierOf(block: Block, program: Program): Reading[] {
	if (!isGroup(block)) return [];
	return program.nodes.find((node) => node.path === block.times)?.edge.readings ?? [];
}

function stepPaths(item: Item): string[] {
	return item.kind === 'step' ? [item.node.path] : item.items.flatMap(stepPaths);
}

function right(box: Box): Point {
	return { x: box.x + box.width, y: box.y + box.height / 2 };
}

function left(box: Box): Point {
	return { x: box.x, y: box.y + box.height / 2 };
}

function top(box: Box): Point {
	return { x: box.x + box.width / 2, y: box.y };
}

function bottom(box: Box): Point {
	return { x: box.x + box.width / 2, y: box.y + box.height };
}

function boxesOf(steps: PlacedStep[], blocks: PlacedBlock[]): Map<string, Box> {
	return new Map([
		...steps.map((step): [string, Box] => [step.path, step.box]),
		...blocks.map((block): [string, Box] => [block.path, block.box])
	]);
}

function around(boxes: Box[], pad: number): Box {
	const x = Math.min(...boxes.map((box) => box.x)) - pad;
	const y = Math.min(...boxes.map((box) => box.y)) - FRAME.header - pad;
	const right = Math.max(...boxes.map((box) => box.x + box.width)) + pad;
	const bottom = Math.max(...boxes.map((box) => box.y + box.height)) + pad;
	return { x, y, width: right - x, height: bottom - y };
}

export function framed(steps: PlacedStep[], blocks: PlacedBlock[]): PlacedBlock[] {
	const fitted = new Map<string, Box>();
	const innermostFirst = [...blocks].sort((a, b) => b.path.length - a.path.length);
	for (const block of innermostFirst) {
		if (block.collapsed) {
			fitted.set(block.path, block.box);
			continue;
		}
		const inside = (path: string) => path.startsWith(`${block.path}/`);
		const nested = innermostFirst.filter(
			(other) =>
				inside(other.path) &&
				!innermostFirst.some(
					(between) =>
						inside(between.path) &&
						between.path !== other.path &&
						other.path.startsWith(`${between.path}/`)
				)
		);
		const direct = steps.filter(
			(step) => inside(step.path) && !nested.some((other) => step.path.startsWith(`${other.path}/`))
		);
		const children = [...direct.map((step) => step.box), ...nested.map((n) => fitted.get(n.path)!)];
		fitted.set(block.path, around(children, FRAME.pad));
	}
	return blocks.map((block) => ({ ...block, box: fitted.get(block.path)! }));
}

function extent(steps: PlacedStep[], blocks: PlacedBlock[], rail: PlacedRule[], gap: number) {
	const boxes = [...steps, ...blocks, ...rail].map((placed) => placed.box);
	return {
		width: Math.max(...boxes.map((box) => box.x + box.width)) + gap + MARGIN,
		height: Math.max(...boxes.map((box) => box.y + box.height)) + MARGIN
	};
}

function wire(
	edges: PlacedEdge[],
	landings: PlacedLanding[],
	steps: PlacedStep[],
	blocks: PlacedBlock[],
	rail: PlacedRule[],
	gap: number
): { edges: PlacedEdge[]; landings: PlacedLanding[] } {
	const boxes = boxesOf(steps, blocks);
	const cards = new Map(rail.map((placed) => [placed.rule.rule, placed.box]));
	return {
		edges: edges.map((edge) => {
			const start = right(boxes.get(edge.from)!);
			const end = edge.to ? left(boxes.get(edge.to)!) : { x: start.x + gap, y: start.y };
			return { ...edge, start, end };
		}),
		landings: landings.map((landing) => ({
			...landing,
			start: top(cards.get(landing.rule)!),
			end: bottom(boxes.get(landing.at)!)
		}))
	};
}

const NOWHERE: Point = { x: 0, y: 0 };

export function layout(program: Program, collapsed: string[], metrics = METRICS): Layout {
	const { node, gap } = metrics;
	const items = tree(program, undefined);
	const levels = depth(items);
	const rowTop = MARGIN + levels * (FRAME.header + FRAME.pad);
	const rowBottom = rowTop + node.height + levels * FRAME.pad;

	const steps: PlacedStep[] = [];
	const placed: PlacedBlock[] = [];
	const standsFor = new Map<string, string>();

	function place(list: Item[], x: number): number {
		let cursor = x;
		for (const item of list) {
			if (item.kind === 'step') {
				const box = { x: cursor, y: rowTop, width: node.width, height: node.height };
				steps.push({ path: item.node.path, node: item.node, box });
				standsFor.set(item.node.path, item.node.path);
				cursor += node.width + gap;
				continue;
			}
			const multiplier = multiplierOf(item.block, program);
			const held = stepPaths(item);
			if (isGroup(item.block) && collapsed.includes(item.block.path)) {
				const box = { x: cursor, y: rowTop, width: node.width, height: node.height };
				placed.push({
					path: item.block.path,
					block: item.block,
					box,
					collapsed: true,
					multiplier,
					steps: held
				});
				for (const path of held) standsFor.set(path, item.block.path);
				cursor += node.width + gap;
				continue;
			}
			const pad = FRAME.pad * (1 + depth(item.items));
			const end = place(item.items, cursor + pad) - gap + pad;
			placed.push({
				path: item.block.path,
				block: item.block,
				box: { x: cursor, y: rowTop, width: end - cursor, height: node.height },
				collapsed: false,
				multiplier,
				steps: held
			});
			cursor = end + gap;
		}
		return cursor;
	}

	place(items, MARGIN);
	const blocks = framed(steps, placed);
	const boxes = boxesOf(steps, blocks);

	const edges: PlacedEdge[] = [];
	const seen = new Set<string>();
	const consumed = new Set<string>();

	for (const step of program.nodes) {
		for (const input of step.inputs) {
			consumed.add(input);
			const from = standsFor.get(input)!;
			const to = standsFor.get(step.path)!;
			if (from === to || seen.has(`${from}>${to}`)) continue;
			seen.add(`${from}>${to}`);
			const source = program.nodes.find((each) => each.path === input)!;
			edges.push({
				kind: 'input',
				from,
				to,
				readings: source.edge.readings,
				start: NOWHERE,
				end: NOWHERE
			});
		}
	}

	for (const group of program.blocks.filter(isGroup)) {
		consumed.add(group.times);
		const from = standsFor.get(group.times)!;
		const to = standsFor.get(group.path) ?? group.path;
		if (from === to || !boxes.has(to)) continue;
		edges.push({
			kind: 'times',
			from,
			to,
			readings: multiplierOf(group, program),
			start: NOWHERE,
			end: NOWHERE
		});
	}

	for (const step of program.nodes) {
		if (consumed.has(step.path)) continue;
		edges.push({
			kind: 'output',
			from: standsFor.get(step.path)!,
			to: null,
			readings: step.edge.readings,
			start: NOWHERE,
			end: NOWHERE
		});
	}

	const modelled = program.rules.filter((rule) => rule.landings.length > 0);
	const unmodelled = program.rules.filter((rule) => rule.landings.length === 0);

	const railTop = rowBottom + RAIL_GAP;
	const wanted = modelled
		.map((rule) => {
			const xs = rule.landings.map((landing) => top(boxes.get(standsFor.get(landing.at)!)!).x);
			return { rule, centre: xs.reduce((sum, x) => sum + x, 0) / xs.length };
		})
		.sort((a, b) => a.centre - b.centre);

	const rail: PlacedRule[] = [];
	let edge = MARGIN;
	for (const { rule, centre } of wanted) {
		const x = Math.max(centre - node.width / 2, edge);
		rail.push({ rule, box: { x, y: railTop, width: node.width, height: RULE.height } });
		edge = x + node.width + RULE.gap;
	}

	const landings: PlacedLanding[] = rail.flatMap(({ rule }) =>
		rule.landings.map((landing) => ({
			rule: rule.rule,
			at: standsFor.get(landing.at)!,
			verdict: landing.verdict,
			start: NOWHERE,
			end: NOWHERE
		}))
	);

	return {
		metrics,
		...extent(steps, blocks, rail, gap),
		steps,
		blocks,
		rail,
		unmodelled,
		...wire(edges, landings, steps, blocks, rail, gap)
	};
}

export function fitted(program: Program, collapsed: string[], available: number): Metrics {
	const natural = layout(program, collapsed, METRICS);
	if (natural.width <= available) return METRICS;
	const columns = natural.steps.length + natural.blocks.filter((block) => block.collapsed).length;
	const gaps = columns - 1 + natural.edges.filter((edge) => edge.kind === 'output').length;
	const scalable = columns * METRICS.node.width + gaps * METRICS.gap;
	const ratio = Math.max(0, (available - (natural.width - scalable)) / scalable);
	return {
		node: {
			width: Math.max(Math.floor(METRICS.node.width * ratio), LEAST.node.width),
			height: METRICS.node.height
		},
		gap: Math.max(Math.floor(METRICS.gap * ratio), LEAST.gap)
	};
}

function shifted(box: Box, by: Point): Box {
	return { ...box, x: box.x + by.x, y: box.y + by.y };
}

function sum(points: Point[]): Point {
	return points.reduce((total, point) => ({ x: total.x + point.x, y: total.y + point.y }), {
		x: 0,
		y: 0
	});
}

export function moved(drawn: Layout, moves: Moves): Layout {
	const of = (path: string) => moves[path] ?? NOWHERE;
	const carriers = (path: string) =>
		drawn.blocks
			.filter((block) => path.startsWith(`${block.path}/`))
			.map((block) => of(block.path));
	const steps = drawn.steps.map((step) => ({
		...step,
		box: shifted(step.box, sum([of(step.path), ...carriers(step.path)]))
	}));
	const blocks = framed(
		steps,
		drawn.blocks.map((block) => ({
			...block,
			box: shifted(block.box, sum([of(block.path), ...carriers(block.path)]))
		}))
	);
	const rail = drawn.rail.map((placed) => ({
		...placed,
		box: shifted(placed.box, of(placed.rule.rule))
	}));
	return {
		...drawn,
		...extent(steps, blocks, rail, drawn.metrics.gap),
		steps,
		blocks,
		rail,
		...wire(drawn.edges, drawn.landings, steps, blocks, rail, drawn.metrics.gap)
	};
}

export function expected(distribution: Distribution): number | null {
	if (distribution.outcomes.some((outcome) => typeof outcome.value !== 'number')) return null;
	return distribution.outcomes.reduce(
		(mean, outcome) => mean + Number(outcome.value) * outcome.p,
		0
	);
}

export function caption(readings: Reading[]): string {
	const first = readings[0];
	if (!first) return '';
	if (!('outcomes' in first)) return `${first.label} ${first.value}`;
	const mean = expected(first);
	return mean === null ? first.label : `${first.label} · ${mean.toFixed(1)}`;
}
