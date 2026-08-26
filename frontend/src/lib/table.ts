import type { MusteredUnit, Wieldable } from './api/client';

/** A standard table, in inches. */
export const TABLE = { width: 72, depth: 48 } as const;

const MM_PER_INCH = 25.4;

/**
 * Which way a block faces, in degrees clockwise from the top of the table.
 *
 * Four facings rather than any angle: a rectangle turned a quarter at a time
 * stays axis-aligned, which is what lets the separation below be an exact
 * edge-to-edge measure rather than an approximation between rotated shapes.
 * Wheeling a unit to an arbitrary angle is not modelled.
 */
export type Facing = 0 | 90 | 180 | 270;

/** A block standing somewhere on the table, in some formation, facing some way. */
export interface Placed {
	id: number;
	block: MusteredUnit;
	/** The centre of the rectangle, in inches from the table's top-left. */
	x: number;
	y: number;
	facing: Facing;
	/** The weapon chosen for close combat; empty leaves the choice to the API. */
	melee: string;
	/** The weapon chosen for shooting; empty leaves the choice to the API. */
	missile: string;
}

/** A unit vector, in table coordinates, where y grows downward. */
interface Vector {
	x: number;
	y: number;
}

/** Where a placed block's front and right point, in table coordinates. */
export function bearing(facing: Facing): { front: Vector; right: Vector } {
	switch (facing) {
		case 0:
			return { front: { x: 0, y: -1 }, right: { x: 1, y: 0 } };
		case 90:
			return { front: { x: 1, y: 0 }, right: { x: 0, y: 1 } };
		case 180:
			return { front: { x: 0, y: 1 }, right: { x: -1, y: 0 } };
		case 270:
			return { front: { x: -1, y: 0 }, right: { x: 0, y: -1 } };
	}
}

/**
 * The block's own dimensions in inches: across its front, and front to back.
 *
 * Read off the footprint the API measured, which is the formation's files and
 * ranks on the datasheet's bases.
 */
export function span(footprint: NonNullable<MusteredUnit['footprint']>): {
	width: number;
	depth: number;
} {
	return { width: footprint.width_mm / MM_PER_INCH, depth: footprint.depth_mm / MM_PER_INCH };
}

/** The axis-aligned rectangle a placed block covers, in inches. */
export function extent(placed: Placed): {
	left: number;
	right: number;
	top: number;
	bottom: number;
	width: number;
	height: number;
} {
	const footprint = placed.block.footprint;
	if (footprint === null) throw new Error(`${placed.block.name} has no footprint to draw`);
	const { width, depth } = span(footprint);
	const sideways = placed.facing === 90 || placed.facing === 270;
	const across = sideways ? depth : width;
	const down = sideways ? width : depth;
	return {
		left: placed.x - across / 2,
		right: placed.x + across / 2,
		top: placed.y - down / 2,
		bottom: placed.y + down / 2,
		width: across,
		height: down
	};
}

/**
 * The gap between two blocks, edge to edge, in inches.
 *
 * What a charge has to cover and what a shot has to carry. Zero when the
 * rectangles touch or overlap, which is what being engaged looks like here.
 */
export function separation(mover: Placed, target: Placed): number {
	const a = extent(mover);
	const b = extent(target);
	const across = Math.max(0, a.left - b.right, b.left - a.right);
	const down = Math.max(0, a.top - b.bottom, b.top - a.bottom);
	return Math.hypot(across, down);
}

/** The arcs a block presents, as the engine names them. */
export type Arc = 'front' | 'flank' | 'rear';

/**
 * Which of the target's arcs the mover stands in.
 *
 * The boundaries are the target's own diagonals, so a wide block presents a
 * wide front and a deep one a wide flank -- the rectangle decides the arcs,
 * not a fixed forty-five degrees.
 */
export function arc(mover: Placed, target: Placed): Arc {
	const footprint = target.block.footprint;
	if (footprint === null) throw new Error(`${target.block.name} has no footprint to face with`);
	const { width, depth } = span(footprint);
	const { front, right } = bearing(target.facing);
	const dx = mover.x - target.x;
	const dy = mover.y - target.y;
	const along = dx * front.x + dy * front.y;
	const across = dx * right.x + dy * right.y;
	// Compared against the half-extents, so the crossover is the diagonal.
	if (Math.abs(along) * width <= Math.abs(across) * depth) return 'flank';
	return along > 0 ? 'front' : 'rear';
}

/** The weapons a block could use in the given phase. */
export function usable(block: MusteredUnit, phase: 'melee' | 'missile'): Wieldable[] {
	return block.weapons.filter((weapon) => (phase === 'melee' ? weapon.fights : weapon.shoots));
}

/** Where a block can be placed without hanging off the table. */
export function within(placed: Placed): boolean {
	const { left, right, top, bottom } = extent(placed);
	return left >= 0 && top >= 0 && right <= TABLE.width && bottom <= TABLE.depth;
}
