import type { ChargeArc, FightBody, LaneUnit } from '$lib/api/client';
import {
	TABLE,
	arc,
	bounds,
	corners,
	refit,
	separation,
	within,
	type Placed as Block
} from '$lib/table';
import { seat } from './body';
import { LANES, type Box, type Lane } from './faces';

/** The two blocks a fight was charged between, by the lane each fights from. */
export type Blocks = Record<Lane, Block>;

/** The blocks as they stand, and the stretch of table, in inches, the crop shows around them. */
export interface Field {
	blocks: Blocks;
	crop: Box;
}

/** The crop's place on the open battlefield, in pixels, and the inches it shows round the blocks. */
export const CROP = { x: 12, y: 34, width: 280, height: 200, margin: 6 };
/** The measurements beside the crop: where their column starts and how wide it is. */
export const BESIDE = { x: CROP.x + CROP.width + 18, width: 110 };

/**
 * The battlefield's size: inputs with no table to measure, read-outs off the
 * table's blocks, and open, the crop of the table with the read-outs beside it.
 */
export function battlefieldSize(mapped: boolean, open: boolean): { width: number; height: number } {
	if (!mapped) return { width: 160, height: 140 };
	if (!open) return { width: 160, height: 78 };
	return { width: BESIDE.x + BESIDE.width + CROP.x, height: CROP.y + CROP.height + CROP.x };
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

/** Where a stretch `extent` long round `centre` starts along a table side, kept on it where it fits. */
function kept(centre: number, extent: number, table: number): number {
	if (extent >= table) return (table - extent) / 2;
	return Math.min(Math.max(centre - extent / 2, 0), table - extent);
}

/** The stretch of table the crop shows, in inches: both blocks with room round them, in its proportions. */
export function cropped(blocks: Blocks): Box {
	const boxes = LANES.map((lane) => bounds(blocks[lane]));
	const left = Math.min(...boxes.map((box) => box.left)) - CROP.margin;
	const right = Math.max(...boxes.map((box) => box.right)) + CROP.margin;
	const top = Math.min(...boxes.map((box) => box.top)) - CROP.margin;
	const bottom = Math.max(...boxes.map((box) => box.bottom)) + CROP.margin;
	const aspect = CROP.width / CROP.height;
	const width = Math.max(right - left, (bottom - top) * aspect);
	const height = width / aspect;
	return {
		x: kept((left + right) / 2, width, TABLE.width),
		y: kept((top + bottom) / 2, height, TABLE.depth),
		width,
		height
	};
}

/** Whether a block dragged in the crop may stand there: on the table, inside the crop, clear of the other. */
export function standable(block: Block, other: Block, crop: Box): boolean {
	const shown = corners(block).every(
		({ x, y }) =>
			x >= crop.x && y >= crop.y && x <= crop.x + crop.width && y <= crop.y + crop.height
	);
	return shown && within(block) && separation(block, other) > 0;
}
