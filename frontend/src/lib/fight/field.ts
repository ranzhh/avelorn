import type { ChargeArc, FightBody, LaneUnit } from '$lib/api/client';
import { arc, refit, separation, type Placed as Block } from '$lib/table';
import { seat } from './body';
import { LANES, type Lane } from './faces';

/** The two blocks a fight was charged between, by the lane each fights from. */
export type Blocks = Record<Lane, Block>;

/** The battlefield's size: inputs with no table to measure, read-outs off the table's blocks. */
export function battlefieldSize(mapped: boolean): { width: number; height: number } {
	return { width: 160, height: mapped ? 78 : 140 };
}

/** The blocks the table resolved a fight between, by lane; null when either is not on the table. */
export function seated(body: FightBody, between: [number, number], placed: Block[]): Blocks | null {
	const [attacker, target] = LANES.map((lane) =>
		placed.find((each) => each.id === between[seat(body, lane) === 'a' ? 0 : 1])
	);
	return attacker && target ? { attacker, target } : null;
}

/** A block re-formed as its unit is fielded, its front rank kept where it stood. */
export function formed(block: Block, unit: LaneUnit): Block {
	if (!unit.base) throw new Error(`${unit.name} has no base`);
	const footprint = {
		files: unit.frontage,
		ranks: unit.ranks,
		width_mm: unit.frontage * unit.base.width_mm,
		depth_mm: unit.ranks * unit.base.depth_mm
	};
	return refit(block, { ...block.block, size: unit.size, footprint });
}

/** The inches the attacker's charge covers, whole as the table rounds them, and the arc it strikes. */
export function measured(blocks: Blocks): { full_inches: number; arc: ChargeArc } {
	return {
		full_inches: Math.round(separation(blocks.attacker, blocks.target)),
		arc: arc(blocks.attacker, blocks.target)
	};
}
