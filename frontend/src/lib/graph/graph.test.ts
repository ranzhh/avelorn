import { describe, expect, it } from 'vitest';

import volley from './volley.json';
import type { Distribution, Program, Reading, Roll } from './types';

const program = volley as Program;
const paths = program.nodes.map((node) => node.path);

const isDistribution = (reading: Reading): reading is Distribution => 'outcomes' in reading;

const rolls = program.nodes.filter((node): node is Roll => node.kind === 'roll');

const distributions = [
	...program.nodes.flatMap((node) => node.edge.readings),
	...rolls.map((roll) => roll.target)
].filter(isDistribution);

describe('the volley fixture', () => {
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

	it('puts every block around at least one node', () => {
		for (const block of program.blocks) {
			expect(paths.some((path) => path.startsWith(`${block.path}/`))).toBe(true);
		}
	});

	it('multiplies every group by an edge that exists', () => {
		for (const block of program.blocks) {
			if (block.kind === 'group') expect(paths).toContain(block.times);
		}
	});

	it('gives every distribution a total mass of one', () => {
		expect(distributions.length).toBeGreaterThan(0);
		for (const distribution of distributions) {
			const total = distribution.outcomes.reduce((sum, outcome) => sum + outcome.p, 0);
			expect(Math.abs(total - 1)).toBeLessThan(1e-9);
		}
	});

	it('gives every roll a target', () => {
		expect(rolls.length).toBeGreaterThan(0);
		for (const roll of rolls) expect(roll.target.label).not.toBe('');
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
