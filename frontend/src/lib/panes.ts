/**
 * The pane stack: what is open over the table, in what order, and where.
 *
 * Kept out of the component because placement is the part a screenshot will not
 * show to be wrong — a pane opened off the bottom of the window looks like a
 * pane that never opened.
 */

/** What a pane reads: anything the corpus files under a printed name. */
export type Subject = 'unit' | 'rule' | 'weapon' | 'armour';

export interface Pane {
	id: number;
	subject: Subject;
	/** The slug addressing the entry, unique per subject among open panes. */
	slug: string;
	title: string;
	/**
	 * The block on the table this was opened for, if any.
	 *
	 * Two blocks of one datasheet read the same entry and hold different
	 * options, so a block's pane is its own pane rather than the datasheet's.
	 */
	block?: number;
	/** Top-left corner in viewport pixels. */
	x: number;
	y: number;
	/**
	 * Where in the stack this sits, highest on top.
	 *
	 * Carried on the pane rather than read off the list's order, because a keyed
	 * list reordered under a pointer moves the node. The browser then has a
	 * pointerdown and a pointerup on different elements, and issues no click.
	 */
	z: number;
}

export interface Size {
	width: number;
	height: number;
}

export interface Viewport {
	width: number;
	height: number;
}

/** What a pane calls itself on its own title bar. */
export const LABEL: Record<Subject, string> = {
	unit: 'datasheet',
	rule: 'rule',
	weapon: 'weapon',
	armour: 'armour'
};

/**
 * What a pane of each subject measures, in pixels.
 *
 * Read by the component into custom properties as well as by the placement
 * below, so the rectangle that is clamped is the rectangle that is drawn. A
 * pane taller than its measure scrolls inside; it does not grow.
 */
export const MEASURE: Record<Subject, Size> = {
	unit: { width: 384, height: 520 },
	rule: { width: 320, height: 300 },
	weapon: { width: 340, height: 340 },
	armour: { width: 300, height: 220 }
};

/** How wide the options a block's pane carries beside its datasheet. */
export const ASIDE = 248;

/**
 * What one pane measures, aside included.
 *
 * A collapsed aside draws narrower than this. Clamping the wider rectangle
 * keeps a pane on screen when it is opened again, and a pane narrower than its
 * clamp cannot overhang.
 */
export function measure(pane: Pick<Pane, 'subject' | 'block'>): Size {
	const base = MEASURE[pane.subject];
	if (pane.block === undefined) return base;
	return { width: base.width + ASIDE, height: base.height };
}

/** How far a pane opened from another sits down and right of it. */
const CASCADE = 24;

/** The corner a cold-opened pane takes, and the step between successive ones. */
const FIRST = { x: 300, y: 72 };
const STEP = 28;

/** A pane dragged off the top or the left is unreachable; this much stays on. */
const GRIP = 40;

/**
 * A corner pulled back inside the window.
 *
 * The bottom and right clamp against the pane's own size, so a whole pane stays
 * visible where there is room for one. The top and left clamp against `GRIP`
 * instead: a tall pane on a short window has to overhang somewhere, and it
 * overhangs the edge you are not holding it by.
 */
export function clamped(
	x: number,
	y: number,
	size: Size,
	viewport: Viewport
): { x: number; y: number } {
	const right = Math.max(GRIP - size.width, viewport.width - size.width);
	const bottom = Math.max(0, viewport.height - size.height);
	return {
		x: Math.min(Math.max(x, GRIP - size.width), right),
		y: Math.min(Math.max(y, 0), Math.max(bottom, 0))
	};
}

/**
 * Where a newly opened pane lands.
 *
 * Opened from another pane it cascades off that one, so the chain of rules you
 * followed to get here reads as a stack. Opened cold it steps down from a fixed
 * corner by how many are already up, so two panes never land exactly on top of
 * each other.
 */
export function spot(
	open: Pane[],
	size: Size,
	viewport: Viewport,
	from?: Pane
): { x: number; y: number } {
	const corner = from
		? { x: from.x + CASCADE, y: from.y + CASCADE }
		: { x: FIRST.x + open.length * STEP, y: FIRST.y + open.length * STEP };
	let landing = clamped(corner.x, corner.y, size, viewport);
	// Step past a corner already taken. Two names followed out of one datasheet
	// cascade off the same parent, so without this the second lands exactly on
	// the first and looks like nothing opened. Bounded by the panes open,
	// because clamping against an edge can stop the stepping from moving.
	for (let tries = 0; tries < open.length && taken(open, landing); tries += 1) {
		landing = clamped(landing.x + CASCADE, landing.y + CASCADE, size, viewport);
	}
	return landing;
}

function taken(open: Pane[], at: { x: number; y: number }): boolean {
	return open.some((pane) => Math.abs(pane.x - at.x) < 2 && Math.abs(pane.y - at.y) < 2);
}

/**
 * Open a pane, or raise the one already reading that entry for that block.
 *
 * A rule opened twice from two datasheets is one pane, because two copies of
 * the same text is not two pieces of information. Two blocks of one datasheet
 * are two panes, because their options differ.
 */
export function opened(
	open: Pane[],
	wanted: { id: number; subject: Subject; slug: string; title: string; block?: number },
	size: Size,
	viewport: Viewport,
	from?: Pane
): Pane[] {
	const already = open.find(
		(pane) =>
			pane.subject === wanted.subject && pane.slug === wanted.slug && pane.block === wanted.block
	);
	if (already) return raised(open, already.id);
	return [...open, { ...wanted, ...spot(open, size, viewport, from), z: ceiling(open) + 1 }];
}

function ceiling(open: Pane[]): number {
	return open.reduce((high, pane) => Math.max(high, pane.z), 0);
}

/** The pane on top, or null with none open. */
export function topmost(open: Pane[]): Pane | null {
	return open.reduce<Pane | null>((top, pane) => (!top || pane.z > top.z ? pane : top), null);
}

/** Bring a pane to the front, leaving the list in the order it opened in. */
export function raised(open: Pane[], id: number): Pane[] {
	const pane = open.find((each) => each.id === id);
	if (!pane || pane.z === ceiling(open)) return open;
	const z = ceiling(open) + 1;
	return open.map((each) => (each.id === id ? { ...each, z } : each));
}

export function closed(open: Pane[], id: number): Pane[] {
	return open.filter((each) => each.id !== id);
}

/** Move a pane to a new corner, kept inside the window. */
export function moved(
	open: Pane[],
	id: number,
	x: number,
	y: number,
	size: Size,
	viewport: Viewport
): Pane[] {
	const settled = clamped(x, y, size, viewport);
	return open.map((pane) => (pane.id === id ? { ...pane, ...settled } : pane));
}
