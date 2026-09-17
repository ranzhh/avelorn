import { describe, expect, it } from 'vitest';

import volley from './volley.json';
import { layout, type Box } from './layout';
import type { Point } from './layout';
import type { Program } from './types';

const program = volley as Program;
const GROUP = 'volley/attack';
const children = program.nodes
	.map((node) => node.path)
	.filter((path) => path.startsWith(`${GROUP}/`));

const expanded = layout(program, []);
const collapsed = layout(program, [GROUP]);

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

describe('layout of the volley', () => {
	it('places the steps in program order, left to right', () => {
		expect(expanded.steps.map((step) => step.path)).toEqual(program.nodes.map((node) => node.path));
		const xs = expanded.steps.map((step) => step.box.x);
		expect([...xs].sort((a, b) => a - b)).toEqual(xs);
		expect(new Set(xs).size).toBe(xs.length);
	});

	it('draws the attack group as a box around its four rolls and nothing else', () => {
		const frame = expanded.blocks.find((block) => block.path === GROUP)!;
		expect(frame.collapsed).toBe(false);
		for (const step of expanded.steps) {
			expect(inside(step.box, frame.box)).toBe(children.includes(step.path));
		}
	});

	it('labels the group with the shots reading', () => {
		const frame = expanded.blocks.find((block) => block.path === GROUP)!;
		expect(frame.multiplier).toEqual([{ label: 'shots', value: 20 }]);
	});

	it('joins consecutive steps by their inputs and carries the source edge', () => {
		const joined = expanded.edges
			.filter((edge) => edge.kind === 'input')
			.map((edge) => [edge.from, edge.to]);
		expect(joined).toEqual(
			program.nodes.flatMap((node) => node.inputs.map((input) => [input, node.path]))
		);
		const toWound = expanded.edges.find((edge) => edge.to === 'volley/attack/roll-to-wound')!;
		expect(toWound.readings[0].label).toBe('hits of 20');
	});

	it('runs the shots count into the group and the panic test out of the program', () => {
		expect(expanded.edges).toContainEqual(
			expect.objectContaining({ kind: 'times', from: 'volley/how-many-shots', to: GROUP })
		);
		expect(expanded.edges).toContainEqual(
			expect.objectContaining({ kind: 'output', from: 'volley/make-panic-tests', to: null })
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
		const paths = collapsed.steps.map((step) => step.path);
		for (const child of children) expect(paths).not.toContain(child);
		const node = collapsed.blocks.find((block) => block.path === GROUP)!;
		expect(node.collapsed).toBe(true);
		expect(node.box.width).toBe(expanded.steps[0].box.width);
		expect(collapsed.width).toBeLessThan(expanded.width);
	});

	it('keeps the edges into and out of the collapsed group', () => {
		expect(collapsed.edges.map((edge) => [edge.kind, edge.from, edge.to])).toEqual([
			['input', GROUP, 'volley/remove-casualties'],
			['input', 'volley/remove-casualties', 'volley/make-panic-tests'],
			['times', 'volley/how-many-shots', GROUP],
			['output', 'volley/make-panic-tests', null]
		]);
		const out = collapsed.edges.find((edge) => edge.from === GROUP)!;
		expect(out.readings[0].label).toBe('unsaved wounds of 20');
	});

	it('lands every rule line on a drawn node, expanded or collapsed', () => {
		for (const drawn of [expanded, collapsed]) {
			expect(drawn.landings.length).toBe(2);
			const boxes = [...drawn.steps.map((s) => s.box), ...drawn.blocks.map((b) => b.box)];
			for (const landing of drawn.landings) {
				expect(boxes.some((box) => onBoundary(landing.end, box))).toBe(true);
				expect(drawn.rail.some((placed) => onBoundary(landing.start, placed.box))).toBe(true);
			}
		}
		expect(collapsed.landings.map((landing) => landing.at)).toEqual([GROUP, GROUP]);
	});

	it('sets a rule with no landing aside as not modelled', () => {
		expect(expanded.unmodelled.map((rule) => rule.rule)).toEqual(['elven-reflexes']);
		expect(expanded.rail.map((placed) => placed.rule.rule)).not.toContain('elven-reflexes');
	});

	it('keeps the rail cards from overlapping', () => {
		const sorted = [...expanded.rail].sort((a, b) => a.box.x - b.box.x);
		for (let index = 1; index < sorted.length; index += 1) {
			const previous = sorted[index - 1].box;
			expect(sorted[index].box.x).toBeGreaterThanOrEqual(previous.x + previous.width);
		}
	});
});
