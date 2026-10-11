import type { Block, Distribution, Judged, Repeat, Node, Program, Reading, Rule } from './types';

export interface Metrics {
	node: { width: number; height: number };
	gap: number;
}

export const METRICS: Metrics = { node: { width: 168, height: 72 }, gap: 64 };
export const LEAST: Metrics = { node: { width: 88, height: 72 }, gap: 32 };
export const FRAME = { pad: 12, header: 24 } as const;
export const MARGIN = 12;
/** The space between two cards stacked in one column. */
export const STACK = 20;
/** A caption's monospace glyph and padding as the canvas draws them, and its clearance. */
export const CAPTION = { glyph: 6.75, pad: 3.2, clear: 8 } as const;
/** The space between the lanes that carry a reading past columns, and their clearance from the cards. */
export const LANE = { step: 6, clear: 16 } as const;

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

/** What one side's steps in a block end on, and every reading they took on the way. */
export interface Summary {
	side: string;
	text: string;
	every: string;
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

/** How an edge passing columns runs: across the gaps beside its ends, and along a lane below the cards. */
export interface Lane {
	index: number;
	out: number;
	back: number;
}

export interface PlacedEdge {
	kind: EdgeKind;
	from: string;
	to: string | null;
	readings: Reading[];
	reach: number;
	lane: Lane | null;
	start: Point;
	via: Point[];
	end: Point;
}

export interface PlacedCaption {
	from: string;
	text: string;
	dx: number;
	at: Point;
}

export interface Layout {
	metrics: Metrics;
	width: number;
	height: number;
	steps: PlacedStep[];
	blocks: PlacedBlock[];
	edges: PlacedEdge[];
	captions: PlacedCaption[];
	unmodelled: Rule[];
}

export type Moves = Record<string, Point>;

type Item = { kind: 'step'; node: Node } | Group;
type Group = { kind: 'block'; block: Block; items: Item[] };

interface Span {
	cols: number;
	rows: number;
}

/** Where an item sits on the grid, and the open frames it sits in. */
interface Cell extends Span {
	item: Item;
	col: number;
	row: number;
	within: Cell[];
}

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

function pathOf(item: Item): string {
	return item.kind === 'step' ? item.node.path : item.block.path;
}

function total(values: number[]): number {
	return values.reduce((sum, value) => sum + value, 0);
}

/** Whether neighbours run side by side: one group for each part a unit attacks with. */
function alongside(a: Item, b: Item): boolean {
	const counter = (item: Item) =>
		item.kind === 'block' && isRepeat(item.block) ? item.block.times : null;
	return counter(a) !== null && counter(a) === counter(b);
}

/** The items in runs that share a column. */
function stages(items: Item[]): Item[][] {
	const runs: Item[][] = [];
	for (const item of items) {
		const run = runs[runs.length - 1];
		if (run && alongside(run[0], item)) run.push(item);
		else runs.push([item]);
	}
	return runs;
}

/**
 * Every item on a grid of columns and rows.
 *
 * Items that run side by side stack down one column, and each run after them
 * takes the next column. A run shorter than its frame is centred in it; a run
 * holding a frame keeps to whole rows.
 */
function grid(items: Item[], open: (item: Item) => item is Group) {
	const cells: Cell[] = [];
	const span = (list: Item[]): Span => {
		const runs = stages(list).map((run) => run.map(size));
		return {
			cols: total(runs.map((sizes) => Math.max(...sizes.map((each) => each.cols)))),
			rows: Math.max(...runs.map((sizes) => total(sizes.map((each) => each.rows))))
		};
	};
	const size = (item: Item): Span => (open(item) ? span(item.items) : { cols: 1, rows: 1 });
	const put = (list: Item[], col: number, row: number, rows: number, within: Cell[]) => {
		for (const run of stages(list)) {
			const sizes = run.map(size);
			const spare = (rows - total(sizes.map((each) => each.rows))) / 2;
			let at = row + (run.some(open) ? Math.floor(spare) : spare);
			run.forEach((item, index) => {
				const cell = { item, col, row: at, ...sizes[index], within };
				cells.push(cell);
				if (open(item)) put(item.items, col, at, cell.rows, [...within, cell]);
				at += cell.rows;
			});
			col += Math.max(...sizes.map((each) => each.cols));
		}
	};
	const whole = span(items);
	put(items, 0, 0, whole.rows, []);
	return { cells, ...whole };
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

/** One caption for what parts side by side end on: under one label, their expected values add up. */
function added(readings: Reading[]): string {
	const { label } = readings[0];
	const means = readings.map((each) => ('outcomes' in each ? expected(each) : null));
	const numbers = means.filter((mean) => mean !== null);
	if (numbers.length < readings.length || readings.some((each) => each.label !== label)) {
		return readings.map((each) => caption([each])).join(' + ');
	}
	return `${label} · ${total(numbers).toFixed(1)}`;
}

/** For each side, what a group's last stage ends on, summed over its parts, and every reading taken. */
function summaryOf(group: Group, sides: string[]): Summary[] {
	return sides.flatMap((side) => {
		const read = (item: Item) =>
			stepsIn(item)
				.filter((step) => step.side === side)
				.flatMap((step) => step.edge.readings);
		const every = group.items.flatMap(read);
		if (!every.length) return [];
		const last = stages(group.items).findLast((run) => run.some((item) => read(item).length));
		const ends = last!.map((item) => read(item).at(-1)).filter((each) => each !== undefined);
		return [{ side, text: added(ends), every: every.map((each) => caption([each])).join(', ') }];
	});
}

function multiplierOf(block: Block, program: Program): Reading[] {
	if (!isRepeat(block)) return [];
	return program.nodes.find((node) => node.path === block.times)?.edge.readings ?? [];
}

function stepsIn(item: Item): Node[] {
	return item.kind === 'step' ? [item.node] : item.items.flatMap(stepsIn);
}

function pathsIn(item: Item): string[] {
	return item.kind === 'step'
		? [item.node.path]
		: [item.block.path, ...item.items.flatMap(pathsIn)];
}

function right(box: Box): Point {
	return { x: box.x + box.width, y: box.y + box.height / 2 };
}

function left(box: Box): Point {
	return { x: box.x, y: box.y + box.height / 2 };
}

/** Where an edge enters an open frame: level with the cards below its header. */
function entry(box: Box): Point {
	return { x: box.x, y: box.y + (box.height + FRAME.header) / 2 };
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

function extent(steps: PlacedStep[], blocks: PlacedBlock[], edges: PlacedEdge[], gap: number) {
	const boxes = [...steps, ...blocks].map((placed) => placed.box);
	const points = edges.flatMap((edge) => [edge.end, ...edge.via]);
	return {
		width:
			Math.max(...boxes.map((box) => box.x + box.width + gap), ...points.map((point) => point.x)) +
			MARGIN,
		height:
			Math.max(...boxes.map((box) => box.y + box.height), ...points.map((point) => point.y)) +
			MARGIN
	};
}

// The svg clips to its own viewport, so nothing may sit left of or above the origin.
function nudge(steps: PlacedStep[], blocks: PlacedBlock[]): Point {
	const boxes = [...steps, ...blocks].map((placed) => placed.box);
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

function entering(blocks: PlacedBlock[], boxes: Map<string, Box>): (path: string) => Point {
	const frames = new Set(blocks.filter((block) => !block.collapsed).map((block) => block.path));
	return (path) => (frames.has(path) ? entry : left)(boxes.get(path)!);
}

/** The corners of an edge on a lane: down the gap after its source, under the cards, up the gap before its reader. */
function bends(start: Point, end: Point, { index, out, back }: Lane, floor: number): Point[] {
	const y = floor + index * LANE.step;
	return [
		{ x: start.x + out, y: start.y },
		{ x: start.x + out, y },
		{ x: end.x - back, y },
		{ x: end.x - back, y: end.y }
	];
}

function wire(
	edges: PlacedEdge[],
	captions: PlacedCaption[],
	steps: PlacedStep[],
	blocks: PlacedBlock[]
): { edges: PlacedEdge[]; captions: PlacedCaption[] } {
	const boxes = boxesOf(steps, blocks);
	const into = entering(blocks, boxes);
	const floor = Math.max(...[...boxes.values()].map((box) => box.y + box.height)) + LANE.clear;
	return {
		edges: edges.map((edge) => {
			const start = right(boxes.get(edge.from)!);
			const end = edge.to ? into(edge.to) : { x: start.x + edge.reach, y: start.y };
			return { ...edge, start, via: edge.lane ? bends(start, end, edge.lane, floor) : [], end };
		}),
		captions: captions.map((each) => {
			const start = right(boxes.get(each.from)!);
			return { ...each, at: { x: start.x + each.dx, y: start.y } };
		})
	};
}

const NOWHERE: Point = { x: 0, y: 0 };

export function grants(program: Program, granter: Rule): Rule[] {
	return program.rules.filter((rule) => rule.sources.some((source) => source.via === granter.id));
}

interface Link {
	kind: EdgeKind;
	from: string;
	to: string;
	readings: Reading[];
}

/**
 * The lane each source's edges past a column share, and the order lanes cross each gap in.
 *
 * A lane runs from the gap after its source to the gap before its furthest
 * reader, and lanes that never meet share a depth. In a gap, the lanes leaving
 * cross nearest their sources, so none runs through another rising.
 */
function lanes(links: Link[], columnOf: Map<string, number>) {
	const spans = new Map<string, { first: number; last: number }>();
	const bands = new Map<number, string[]>();
	const cross = (col: number, from: string) => {
		const band = bands.get(col) ?? [];
		if (!band.includes(from)) bands.set(col, [...band, from]);
	};
	for (const { from, to } of links) {
		const last = columnOf.get(to)! - 1;
		spans.set(from, {
			first: columnOf.get(from)!,
			last: Math.max(last, spans.get(from)?.last ?? last)
		});
	}
	for (const [from, { first }] of spans) cross(first, from);
	for (const { from, to } of links) cross(columnOf.get(to)! - 1, from);
	const depths = new Map<string, number>();
	const ends: number[] = [];
	for (const [from, { first, last }] of [...spans].sort((a, b) => a[1].first - b[1].first)) {
		const free = ends.findIndex((end) => end < first);
		const depth = free < 0 ? ends.length : free;
		ends[depth] = last;
		depths.set(from, depth);
	}
	return { depths, bands };
}

/**
 * Where each column and row of the grid starts, and where a lane crosses the gap after a column.
 *
 * The gap after a column holds its widest caption, then the lanes crossing it,
 * and the frames closing around it and opening around the next.
 */
function measure(
	cards: Cell[],
	cols: number,
	rows: number,
	{ node, gap }: Metrics,
	bands: Map<number, string[]>
) {
	const framing = (axis: 'col' | 'row', index: number, closing: boolean) => {
		const edge = (frame: Cell) =>
			closing ? frame[axis] + (axis === 'col' ? frame.cols : frame.rows) - 1 : frame[axis];
		return Math.max(
			0,
			...cards
				.filter((card) => card[axis] === index)
				.map((card) => card.within.filter((frame) => edge(frame) === index).length)
		);
	};
	const text = (item: Item) => (item.kind === 'step' ? caption(item.node.edge.readings) : '');
	const rooms = Array.from({ length: cols }, (_, col) =>
		Math.max(
			gap,
			...cards.filter((card) => card.col === col).map((card) => room(text(card.item), gap))
		)
	);
	const crossing = (col: number) => bands.get(col) ?? [];
	const band = (col: number) =>
		crossing(col).length ? LANE.step * crossing(col).length + LANE.clear : 0;
	const lefts: number[] = [];
	for (let col = 0, x = MARGIN + FRAME.pad * framing('col', 0, false); col < cols; col++) {
		lefts.push(x);
		const pads = framing('col', col, true) + framing('col', col + 1, false);
		x += node.width + FRAME.pad * pads + rooms[col] + band(col);
	}
	const tops: number[] = [];
	for (
		let row = 0, y = MARGIN + (FRAME.header + FRAME.pad) * framing('row', 0, false);
		row <= rows;
		row++
	) {
		tops.push(y);
		y +=
			node.height +
			FRAME.pad * framing('row', row, true) +
			STACK +
			(FRAME.header + FRAME.pad) * framing('row', row + 1, false);
	}
	const top = (row: number) => {
		const whole = Math.floor(row);
		return tops[whole] + (row - whole) * (tops[whole + 1] - tops[whole]);
	};
	const centre = (col: number) => FRAME.pad * framing('col', col, true) + rooms[col] / 2;
	const slot = (col: number, from: string) =>
		FRAME.pad * framing('col', col, true) +
		rooms[col] +
		LANE.step * (crossing(col).indexOf(from) + 0.5);
	return { lefts, top, centre, slot };
}

export function layout(program: Program, collapsed: string[], metrics = METRICS): Layout {
	const { node, gap } = metrics;
	const open = (item: Item): item is Group =>
		item.kind === 'block' && !collapsed.includes(item.block.path);
	const { cells, cols, rows } = grid(tree(program, undefined), open);
	const columnOf = new Map(cells.map((cell) => [pathOf(cell.item), cell.col]));
	const standsFor = new Map<string, string>();
	for (const cell of cells) {
		const held = open(cell.item) ? [cell.item.block.path] : pathsIn(cell.item);
		for (const each of held) standsFor.set(each, pathOf(cell.item));
	}

	const links: Link[] = [];
	const seen = new Set<string>();
	const link = (kind: EdgeKind, from: string, to: string, readings: Reading[]) => {
		if (from === to || seen.has(`${from}>${to}`)) return;
		seen.add(`${from}>${to}`);
		links.push({ kind, from, to, readings });
	};
	for (const step of program.nodes) {
		for (const input of step.inputs) {
			const source = program.nodes.find((each) => each.path === input)!;
			link('input', standsFor.get(input)!, standsFor.get(step.path)!, source.edge.readings);
		}
	}
	for (const group of program.blocks.filter(isRepeat)) {
		const to = standsFor.get(group.path)!;
		link('times', standsFor.get(group.times)!, to, multiplierOf(group, program));
	}
	const span = (each: Link) => columnOf.get(each.to)! - columnOf.get(each.from)!;
	const forward = links.filter((each) => span(each) > 0);
	const { depths, bands } = lanes(
		forward.filter((each) => span(each) > 1),
		columnOf
	);
	const { lefts, top, centre, slot } = measure(
		cells.filter((cell) => !open(cell.item)),
		cols,
		rows,
		metrics,
		bands
	);

	const steps: PlacedStep[] = [];
	const placed: PlacedBlock[] = [];
	for (const cell of cells) {
		const box = { x: lefts[cell.col], y: top(cell.row), width: node.width, height: node.height };
		const path = pathOf(cell.item);
		if (cell.item.kind === 'step') {
			steps.push({ path, node: cell.item.node, box });
			continue;
		}
		placed.push({
			path,
			block: cell.item.block,
			box,
			collapsed: !open(cell.item),
			multiplier: multiplierOf(cell.item.block, program),
			summary: summaryOf(cell.item, program.sides),
			steps: stepsIn(cell.item).map((step) => step.path)
		});
	}

	const blocks = framed(steps, placed);
	const into = entering(blocks, boxesOf(steps, blocks));
	const edges: PlacedEdge[] = forward.map((each) => {
		const [from, to] = [columnOf.get(each.from)!, columnOf.get(each.to)!];
		const rise = lefts[to - 1] + node.width + slot(to - 1, each.from);
		const lane =
			to - from > 1
				? {
						index: depths.get(each.from)!,
						out: slot(from, each.from),
						back: into(each.to).x - rise
					}
				: null;
		return { ...each, reach: 0, lane, start: NOWHERE, via: [], end: NOWHERE };
	});
	const sending = new Set(links.map((each) => each.from));
	for (const step of steps) {
		if (sending.has(step.path) || !caption(step.node.edge.readings)) continue;
		edges.push({
			kind: 'output',
			from: step.path,
			to: null,
			readings: step.node.edge.readings,
			reach: centre(columnOf.get(step.path)!),
			lane: null,
			start: NOWHERE,
			via: [],
			end: NOWHERE
		});
	}
	const captions = [...captioned(edges, blocks)].map(([from, text]) => ({
		from,
		text,
		dx: centre(columnOf.get(from)!),
		at: NOWHERE
	}));

	const wired = wire(edges, captions, steps, blocks);
	return {
		metrics,
		...extent(steps, blocks, wired.edges, gap),
		steps,
		blocks,
		unmodelled: unmodelled(program),
		...wired
	};
}

/** The rules that land on no step, nor grant a rule that does. */
function unmodelled(program: Program): Rule[] {
	const modelled = new Set(program.rules.filter((rule) => rule.landings.length).map((r) => r.id));
	for (let grown = true; grown;) {
		const next = program.rules.filter(
			(rule) =>
				!modelled.has(rule.id) && grants(program, rule).some((each) => modelled.has(each.id))
		);
		for (const rule of next) modelled.add(rule.id);
		grown = next.length > 0;
	}
	return program.rules.filter((rule) => !modelled.has(rule.id));
}

/** Whether a rule applied in any of the worlds a landing was judged in. */
export function applied(verdicts: Judged[]): boolean {
	return verdicts.some((each) => each.verdict === 'applied' && each.p > 0);
}

/** The rules that land on a step, each with whether it applied there. */
export function landed(program: Program, path: string): { rule: Rule; applied: boolean }[] {
	return program.rules.flatMap((rule) =>
		rule.landings
			.filter((landing) => landing.at === path)
			.map((landing) => ({ rule, applied: applied(landing.verdicts) }))
	);
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
	const by = nudge(dragged, reframed);
	const steps = dragged.map((step) => ({ ...step, box: shifted(step.box, by) }));
	const blocks = reframed.map((block) => ({ ...block, box: shifted(block.box, by) }));
	const wired = wire(drawn.edges, drawn.captions, steps, blocks);
	return {
		...drawn,
		...extent(steps, blocks, wired.edges, drawn.metrics.gap),
		steps,
		blocks,
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
