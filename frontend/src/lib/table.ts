import type { MusteredUnit, Wieldable } from './api/client';

/** A standard table, in inches. */
export const TABLE = { width: 72, depth: 48 } as const;

const MM_PER_INCH = 25.4;

/**
 * Which way a block faces: degrees clockwise from the top of the table.
 *
 * Any angle. Blocks are turned by a rotation handle rather than a quarter at a
 * time, so nothing here may assume an axis-aligned rectangle -- which is why
 * `separation` measures between polygons rather than between bounding boxes.
 */
export type Degrees = number;

/**
 * A short name for the nth block put on the table: A, B, ... Z, AA, AB.
 *
 * A rectangle is too small for "Elven Spearmen", and a model count does not
 * identify anything once two blocks of twenty are standing on the table.
 */
export function identifier(nth: number): string {
	let mark = '';
	let left = nth;
	while (left >= 0) {
		mark = String.fromCharCode(65 + (left % 26)) + mark;
		left = Math.floor(left / 26) - 1;
	}
	return mark;
}

/** A block standing somewhere on the table, in some formation, facing some way. */
export interface Placed {
	id: number;
	/** What the block is called on the table: A, B, C. */
	mark: string;
	block: MusteredUnit;
	/** The centre of the rectangle, in inches from the table's top-left. */
	x: number;
	y: number;
	facing: Degrees;
	/** The weapon chosen for close combat; empty leaves the choice to the API. */
	melee: string;
	/** The weapon chosen for shooting; empty leaves the choice to the API. */
	missile: string;
}

export interface Point {
	x: number;
	y: number;
}

/** Where a block's front and right point, in table coordinates, where y grows down. */
export function bearing(facing: Degrees): { front: Point; right: Point } {
	const radians = (facing * Math.PI) / 180;
	return {
		front: { x: Math.sin(radians), y: -Math.cos(radians) },
		right: { x: Math.cos(radians), y: Math.sin(radians) }
	};
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

function measured(placed: Placed): { width: number; depth: number } {
	const footprint = placed.block.footprint;
	if (!footprint) throw new Error(`${placed.block.name} has no footprint`);
	return span(footprint);
}

/** The four corners of a placed block, clockwise from its front-right. */
export function corners(placed: Placed): Point[] {
	const { width, depth } = measured(placed);
	const { front, right } = bearing(placed.facing);
	const halfWidth = width / 2;
	const halfDepth = depth / 2;
	return [
		[1, 1],
		[1, -1],
		[-1, -1],
		[-1, 1]
	].map(([across, along]) => ({
		x: placed.x + right.x * across * halfWidth + front.x * along * halfDepth,
		y: placed.y + right.y * across * halfWidth + front.y * along * halfDepth
	}));
}

/** The axis-aligned box the block's corners fit inside, in inches. */
export function bounds(placed: Placed): {
	left: number;
	right: number;
	top: number;
	bottom: number;
	width: number;
	height: number;
} {
	const points = corners(placed);
	const xs = points.map((point) => point.x);
	const ys = points.map((point) => point.y);
	const left = Math.min(...xs);
	const right = Math.max(...xs);
	const top = Math.min(...ys);
	const bottom = Math.max(...ys);
	return { left, right, top, bottom, width: right - left, height: bottom - top };
}

/** Whether a block stands clear of the table's edges. */
export function within(placed: Placed): boolean {
	return corners(placed).every(
		(point) => point.x >= 0 && point.y >= 0 && point.x <= TABLE.width && point.y <= TABLE.depth
	);
}

function edges(points: Point[]): [Point, Point][] {
	return points.map((point, index) => [point, points[(index + 1) % points.length]]);
}

/** Whether two convex polygons share any area, by separating axis. */
function overlapping(one: Point[], two: Point[]): boolean {
	for (const polygon of [one, two]) {
		for (const [from, to] of edges(polygon)) {
			const axis = { x: -(to.y - from.y), y: to.x - from.x };
			const project = (points: Point[]) => points.map((p) => p.x * axis.x + p.y * axis.y);
			const a = project(one);
			const b = project(two);
			if (Math.max(...a) < Math.min(...b) || Math.max(...b) < Math.min(...a)) return false;
		}
	}
	return true;
}

function pointToSegment(point: Point, from: Point, to: Point): number {
	const dx = to.x - from.x;
	const dy = to.y - from.y;
	const length = dx * dx + dy * dy;
	const t =
		length === 0
			? 0
			: Math.max(0, Math.min(1, ((point.x - from.x) * dx + (point.y - from.y) * dy) / length));
	return Math.hypot(point.x - (from.x + t * dx), point.y - (from.y + t * dy));
}

function segmentToSegment(a: [Point, Point], b: [Point, Point]): number {
	return Math.min(
		pointToSegment(a[0], b[0], b[1]),
		pointToSegment(a[1], b[0], b[1]),
		pointToSegment(b[0], a[0], a[1]),
		pointToSegment(b[1], a[0], a[1])
	);
}

/**
 * The gap between two blocks, edge to edge, in inches.
 *
 * What a charge has to cover and what a shot has to carry. Zero when the
 * rectangles touch or overlap, which is what being engaged looks like here.
 * Measured between the rectangles themselves rather than their bounding boxes,
 * so a block turned off the axis is not reported as wider than it is.
 */
export function separation(mover: Placed, target: Placed): number {
	const one = corners(mover);
	const two = corners(target);
	if (overlapping(one, two)) return 0;
	let least = Infinity;
	for (const a of edges(one)) {
		for (const b of edges(two)) {
			least = Math.min(least, segmentToSegment(a, b));
		}
	}
	return least;
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
	const { width, depth } = measured(target);
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

/** The angle from a block's centre to a point, in degrees clockwise from the top. */
export function angleTo(centre: Point, at: Point): Degrees {
	const degrees = (Math.atan2(at.x - centre.x, centre.y - at.y) * 180) / Math.PI;
	return (degrees + 360) % 360;
}

/** The base a single model stands on, in inches, read back out of the footprint. */
export function base(footprint: NonNullable<MusteredUnit['footprint']>): {
	width: number;
	depth: number;
} {
	const { width, depth } = span(footprint);
	return { width: width / footprint.files, depth: depth / footprint.ranks };
}

/**
 * The frontage a block would take if its side edge were dragged to `across`.
 *
 * `across` is the distance from the block's centre to the pointer along its own
 * width, so half the formation. Bounded at one file and at the model count: a
 * block cannot stand narrower than a single file, and standing wider than it
 * has models is the same as one rank.
 */
export function reformed(
	footprint: NonNullable<MusteredUnit['footprint']>,
	models: number,
	across: number
): number {
	const files = Math.round((Math.abs(across) * 2) / base(footprint).width);
	return Math.min(Math.max(files, 1), models);
}

/** An angle snapped to the nearest `step` degrees. */
export function snap(facing: Degrees, step = 15): Degrees {
	return (((Math.round(facing / step) * step) % 360) + 360) % 360;
}

/**
 * Somewhere the block can stand, working outward from a preferred spot.
 *
 * Deploying puts a block straight onto the table, so it has to land somewhere
 * legal without being asked: the first free spot on a widening ring around the
 * near edge, or the preferred spot itself if the table is too crowded to place
 * it clear.
 */
export function room(candidate: Placed, taken: Placed[]): Placed {
	const rings = [0, 3, 6, 9, 12, 15, 18];
	for (const radius of rings) {
		for (let turn = 0; turn < 12; turn += 1) {
			const angle = (turn / 12) * 2 * Math.PI;
			const trial = {
				...candidate,
				x: candidate.x + Math.sin(angle) * radius,
				y: candidate.y - Math.cos(angle) * radius
			};
			if (!within(trial)) continue;
			if (taken.every((other) => separation(trial, other) > 0.5)) return trial;
			if (radius === 0) break;
		}
	}
	return candidate;
}
