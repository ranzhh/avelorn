import type { Block, Group, Node, Program, Reading, Rule, Verdict } from './types';

export const NODE = { width: 168, height: 128 } as const;
export const EDGE_GAP = 128;
export const FRAME = { pad: 16, header: 24 } as const;
export const RULE = { width: 168, height: 56, gap: 24 } as const;
export const RAIL_GAP = 120;
export const MARGIN = 16;

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
	width: number;
	height: number;
	steps: PlacedStep[];
	blocks: PlacedBlock[];
	edges: PlacedEdge[];
	rail: PlacedRule[];
	landings: PlacedLanding[];
	unmodelled: Rule[];
}

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

export function layout(program: Program, collapsed: string[]): Layout {
	const items = tree(program, undefined);
	const levels = depth(items);
	const rowTop = MARGIN + levels * (FRAME.header + FRAME.pad);
	const rowBottom = rowTop + NODE.height + levels * FRAME.pad;

	const steps: PlacedStep[] = [];
	const blocks: PlacedBlock[] = [];
	const boxes = new Map<string, Box>();
	const standsFor = new Map<string, string>();

	function place(list: Item[], x: number): number {
		let cursor = x;
		for (const item of list) {
			if (item.kind === 'step') {
				const box = { x: cursor, y: rowTop, width: NODE.width, height: NODE.height };
				steps.push({ path: item.node.path, node: item.node, box });
				boxes.set(item.node.path, box);
				standsFor.set(item.node.path, item.node.path);
				cursor += NODE.width + EDGE_GAP;
				continue;
			}
			const multiplier = multiplierOf(item.block, program);
			if (isGroup(item.block) && collapsed.includes(item.block.path)) {
				const box = { x: cursor, y: rowTop, width: NODE.width, height: NODE.height };
				blocks.push({ path: item.block.path, block: item.block, box, collapsed: true, multiplier });
				boxes.set(item.block.path, box);
				for (const path of stepPaths(item)) standsFor.set(path, item.block.path);
				cursor += NODE.width + EDGE_GAP;
				continue;
			}
			const inner = 1 + depth(item.items);
			const pad = FRAME.pad * inner;
			const end = place(item.items, cursor + pad) - EDGE_GAP + pad;
			const y = rowTop - (FRAME.header + FRAME.pad) * inner;
			const box = { x: cursor, y, width: end - cursor, height: rowTop + NODE.height + pad - y };
			blocks.push({ path: item.block.path, block: item.block, box, collapsed: false, multiplier });
			boxes.set(item.block.path, box);
			cursor = end + EDGE_GAP;
		}
		return cursor;
	}

	const flowEnd = place(items, MARGIN) - EDGE_GAP;

	const edges: PlacedEdge[] = [];
	const seen = new Set<string>();
	const consumed = new Set<string>();
	const groups = program.blocks.filter(isGroup);

	for (const node of program.nodes) {
		for (const input of node.inputs) {
			consumed.add(input);
			const from = standsFor.get(input)!;
			const to = standsFor.get(node.path)!;
			if (from === to || seen.has(`${from}>${to}`)) continue;
			seen.add(`${from}>${to}`);
			const source = program.nodes.find((each) => each.path === input)!;
			edges.push({
				kind: 'input',
				from,
				to,
				readings: source.edge.readings,
				start: right(boxes.get(from)!),
				end: left(boxes.get(to)!)
			});
		}
	}

	for (const group of groups) {
		consumed.add(group.times);
		const from = standsFor.get(group.times)!;
		const to = standsFor.get(group.path) ?? group.path;
		if (from === to || !boxes.has(to)) continue;
		const target = boxes.get(to)!;
		const end = blocks.find((each) => each.path === to)!.collapsed
			? left(target)
			: { x: target.x, y: rowTop + NODE.height / 2 };
		edges.push({
			kind: 'times',
			from,
			to,
			readings: multiplierOf(group, program),
			start: right(boxes.get(from)!),
			end
		});
	}

	for (const node of program.nodes) {
		if (consumed.has(node.path)) continue;
		const from = standsFor.get(node.path)!;
		const start = right(boxes.get(from)!);
		edges.push({
			kind: 'output',
			from,
			to: null,
			readings: node.edge.readings,
			start,
			end: { x: start.x + EDGE_GAP, y: start.y }
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
		const x = Math.max(centre - RULE.width / 2, edge);
		rail.push({ rule, box: { x, y: railTop, width: RULE.width, height: RULE.height } });
		edge = x + RULE.width + RULE.gap;
	}

	const landings: PlacedLanding[] = rail.flatMap(({ rule, box }) =>
		rule.landings.map((landing) => ({
			rule: rule.rule,
			at: standsFor.get(landing.at)!,
			verdict: landing.verdict,
			start: top(box),
			end: bottom(boxes.get(standsFor.get(landing.at)!)!)
		}))
	);

	const width =
		Math.max(flowEnd + EDGE_GAP, ...rail.map((each) => each.box.x + each.box.width)) + MARGIN;
	const height = (rail.length ? railTop + RULE.height : rowBottom) + MARGIN;

	return { width, height, steps, blocks, edges, rail, landings, unmodelled };
}
