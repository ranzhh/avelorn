import type { Block, Distribution, Judged, Repeat, Node, Program, Reading, Rule } from './types';

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
/** A caption's monospace glyph and padding as the canvas draws them, and its clearance. */
export const CAPTION = { glyph: 6.75, pad: 3.2, clear: 8 } as const;

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

/** What one side's steps in a block read, one glimpse after another. */
export interface Summary {
	side: string;
	text: string;
}

export interface PlacedBlock {
	path: string;
	block: Block;
	box: Box;
	collapsed: boolean;
	multiplier: Reading[];
	summary: Summary[];
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

export interface PlacedCaption {
	text: string;
	at: Point;
}

export interface PlacedRule {
	rule: Rule;
	box: Box;
}

export interface PlacedLanding {
	rule: string;
	at: string;
	verdicts: Judged[];
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
	captions: PlacedCaption[];
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

function isRepeat(block: Block): block is Repeat {
	return block.kind === 'repeat';
}

/** Whether a block may be drawn as one card; a decision's body stays open. */
export function foldable(block: Block): boolean {
	return block.kind !== 'body';
}

/** Whether a block starts as one card: a slot does, a sequence or repeat as its program says. */
export function startsFolded(block: Block): boolean {
	if (block.kind === 'slot') return true;
	return block.kind !== 'body' && block.collapsed;
}

function glimpse(reading: Reading): string {
	if (!('outcomes' in reading)) return `${reading.label} ${reading.value}`;
	const values = reading.outcomes.map((outcome) => outcome.value);
	if (!values.length) return '';
	const first = values[0];
	const last = values[values.length - 1];
	return `${reading.label} ${first === last ? first : `${first}–${last}`}`;
}

function summaryOf(paths: string[], program: Program): Summary[] {
	const held = new Set(paths);
	const steps = program.nodes.filter((node) => held.has(node.path));
	return program.sides
		.map((side) => ({
			side,
			text: steps
				.filter((step) => step.side === side)
				.flatMap((step) => step.edge.readings.map(glimpse))
				.filter(Boolean)
				.join(' · ')
		}))
		.filter((summary) => summary.text);
}

function multiplierOf(block: Block, program: Program): Reading[] {
	if (!isRepeat(block)) return [];
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

function extent(
	steps: PlacedStep[],
	blocks: PlacedBlock[],
	rail: PlacedRule[],
	edges: PlacedEdge[],
	gap: number
) {
	const boxes = [...steps, ...blocks, ...rail].map((placed) => placed.box);
	return {
		width:
			Math.max(...boxes.map((box) => box.x + box.width + gap), ...edges.map((edge) => edge.end.x)) +
			MARGIN,
		height: Math.max(...boxes.map((box) => box.y + box.height)) + MARGIN
	};
}

// The svg clips to its own viewport, so nothing may sit left of or above the origin.
function nudge(steps: PlacedStep[], blocks: PlacedBlock[], rail: PlacedRule[]): Point {
	const boxes = [...steps, ...blocks, ...rail].map((placed) => placed.box);
	return {
		x: MARGIN - Math.min(MARGIN, ...boxes.map((box) => box.x)),
		y: MARGIN - Math.min(MARGIN, ...boxes.map((box) => box.y))
	};
}

/** The gap after a step, widened to hold its caption clear of the cards on either side. */
function room(text: string, gap: number): number {
	if (!text) return gap;
	return Math.max(gap, text.length * CAPTION.glyph + 2 * (CAPTION.pad + CAPTION.clear));
}

/**
 * What leaves each step, captioned once however far its edges run.
 *
 * A folded block's card already sums up its readings, so what leaves it goes uncaptioned.
 */
function captioned(edges: PlacedEdge[], blocks: PlacedBlock[]): Map<string, string> {
	const cards = new Set(blocks.filter((block) => block.collapsed).map((block) => block.path));
	const texts = new Map<string, string>();
	for (const edge of edges) {
		const text = caption(edge.readings);
		if (text && !cards.has(edge.from) && !texts.has(edge.from)) texts.set(edge.from, text);
	}
	return texts;
}

function wire(
	edges: PlacedEdge[],
	landings: PlacedLanding[],
	steps: PlacedStep[],
	blocks: PlacedBlock[],
	rail: PlacedRule[],
	gap: number
): { edges: PlacedEdge[]; captions: PlacedCaption[]; landings: PlacedLanding[] } {
	const boxes = boxesOf(steps, blocks);
	const cards = new Map(rail.map((placed) => [placed.rule.id, placed.box]));
	const texts = captioned(edges, blocks);
	return {
		edges: edges.map((edge) => {
			const start = right(boxes.get(edge.from)!);
			const after = room(texts.get(edge.from) ?? '', gap);
			const end = edge.to ? left(boxes.get(edge.to)!) : { x: start.x + after, y: start.y };
			return { ...edge, start, end };
		}),
		captions: [...texts].map(([from, text]) => {
			const start = right(boxes.get(from)!);
			return { text, at: { x: start.x + room(text, gap) / 2, y: start.y } };
		}),
		landings: landings.map((landing) => ({
			...landing,
			start: top(cards.get(landing.rule)!),
			end: bottom(boxes.get(landing.at)!)
		}))
	};
}

const NOWHERE: Point = { x: 0, y: 0 };

export function grants(program: Program, granter: Rule): Rule[] {
	return program.rules.filter((rule) => rule.sources.some((source) => source.via === granter.id));
}

export function layout(program: Program, collapsed: string[], metrics = METRICS): Layout {
	const { node, gap } = metrics;
	const items = tree(program, undefined);
	const levels = depth(items);
	const rowTop = MARGIN + levels * (FRAME.header + FRAME.pad);
	const rowBottom = rowTop + node.height + levels * FRAME.pad;

	const steps: PlacedStep[] = [];
	const placed: PlacedBlock[] = [];
	const standsFor = new Map<string, string>();

	function place(list: Item[], x: number): { end: number; after: number } {
		let end = x;
		let after = 0;
		for (const item of list) {
			const at = end + after;
			if (item.kind === 'step') {
				const box = { x: at, y: rowTop, width: node.width, height: node.height };
				steps.push({ path: item.node.path, node: item.node, box });
				standsFor.set(item.node.path, item.node.path);
				end = at + node.width;
				after = room(caption(item.node.edge.readings), gap);
				continue;
			}
			const multiplier = multiplierOf(item.block, program);
			const held = stepPaths(item);
			if (collapsed.includes(item.block.path)) {
				const box = { x: at, y: rowTop, width: node.width, height: node.height };
				placed.push({
					path: item.block.path,
					block: item.block,
					box,
					collapsed: true,
					multiplier,
					summary: summaryOf(held, program),
					steps: held
				});
				for (const path of held) standsFor.set(path, item.block.path);
				end = at + node.width;
				after = gap;
				continue;
			}
			const pad = FRAME.pad * (1 + depth(item.items));
			const inner = place(item.items, at + pad);
			end = inner.end + pad;
			after = Math.max(gap, inner.after - pad);
			placed.push({
				path: item.block.path,
				block: item.block,
				box: { x: at, y: rowTop, width: end - at, height: node.height },
				collapsed: false,
				multiplier,
				summary: summaryOf(held, program),
				steps: held
			});
		}
		return { end, after };
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

	for (const group of program.blocks.filter(isRepeat)) {
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

	const rows = [program.rules.filter((rule) => rule.landings.length > 0)];
	const modelled = new Set(rows[0].map((rule) => rule.id));
	while (rows[rows.length - 1].length) {
		const next = program.rules.filter(
			(rule) =>
				!modelled.has(rule.id) && grants(program, rule).some((each) => modelled.has(each.id))
		);
		for (const rule of next) modelled.add(rule.id);
		rows.push(next);
	}
	const unmodelled = program.rules.filter((rule) => !modelled.has(rule.id));

	const railTop = rowBottom + RAIL_GAP;
	const centres = new Map<string, number>();
	const rail: PlacedRule[] = [];
	rows.forEach((row, depth) => {
		const wanted = row
			.map((rule) => {
				const xs = depth
					? grants(program, rule)
							.filter((each) => centres.has(each.id))
							.map((each) => centres.get(each.id)!)
					: rule.landings.map((landing) => top(boxes.get(standsFor.get(landing.at)!)!).x);
				return { rule, centre: xs.reduce((sum, x) => sum + x, 0) / xs.length };
			})
			.sort((a, b) => a.centre - b.centre);
		const y = railTop + depth * (RULE.height + RULE.gap);
		let edge = MARGIN;
		for (const { rule, centre } of wanted) {
			const x = Math.max(centre - node.width / 2, edge);
			rail.push({ rule, box: { x, y, width: node.width, height: RULE.height } });
			centres.set(rule.id, x + node.width / 2);
			edge = x + node.width + RULE.gap;
		}
	});

	const landings: PlacedLanding[] = rail.flatMap(({ rule }) =>
		rule.landings.map((landing) => ({
			rule: rule.id,
			at: standsFor.get(landing.at)!,
			verdicts: landing.verdicts,
			start: NOWHERE,
			end: NOWHERE
		}))
	);

	const wired = wire(edges, landings, steps, blocks, rail, gap);
	return {
		metrics,
		...extent(steps, blocks, rail, wired.edges, gap),
		steps,
		blocks,
		rail,
		unmodelled,
		...wired
	};
}

/**
 * The widest metrics at which the program fits the width available.
 *
 * Squeezing is worth it only when it spares the scroll; when even the floor
 * overflows, the cards keep their full size. Between the floor and full size the
 * drawing widens no faster than the straight line joining them, so a share of
 * the way along that line always fits.
 */
export function fitted(program: Program, collapsed: string[], available: number): Metrics {
	const widest = layout(program, collapsed, METRICS).width;
	if (widest <= available) return METRICS;
	const narrowest = layout(program, collapsed, LEAST).width;
	if (narrowest > available) return METRICS;
	const share = (available - narrowest) / (widest - narrowest);
	const between = (least: number, most: number) => Math.floor(least + share * (most - least));
	return {
		node: { width: between(LEAST.node.width, METRICS.node.width), height: METRICS.node.height },
		gap: between(LEAST.gap, METRICS.gap)
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
	const dragged = drawn.steps.map((step) => ({
		...step,
		box: shifted(step.box, sum([of(step.path), ...carriers(step.path)]))
	}));
	const reframed = framed(
		dragged,
		drawn.blocks.map((block) => ({
			...block,
			box: shifted(block.box, sum([of(block.path), ...carriers(block.path)]))
		}))
	);
	const carded = drawn.rail.map((placed) => ({
		...placed,
		box: shifted(placed.box, of(placed.rule.id))
	}));
	const by = nudge(dragged, reframed, carded);
	const steps = dragged.map((step) => ({ ...step, box: shifted(step.box, by) }));
	const blocks = reframed.map((block) => ({ ...block, box: shifted(block.box, by) }));
	const rail = carded.map((placed) => ({ ...placed, box: shifted(placed.box, by) }));
	const wired = wire(drawn.edges, drawn.landings, steps, blocks, rail, drawn.metrics.gap);
	return {
		...drawn,
		...extent(steps, blocks, rail, wired.edges, drawn.metrics.gap),
		steps,
		blocks,
		rail,
		...wired
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
