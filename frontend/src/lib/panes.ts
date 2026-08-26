/**
 * The pane stack: what is open over the table, in what order, and where.
 *
 * Kept out of the component because placement is the part a screenshot will not
 * show to be wrong — a pane opened off the bottom of the window looks like a
 * pane that never opened.
 */

/** What a pane reads. A datasheet, or one of the rules it prints. */
export type Subject = 'unit' | 'rule';

export interface Pane {
	id: number;
	subject: Subject;
	/** The slug addressing the entry, unique per subject among open panes. */
	slug: string;
	title: string;
	/** Top-left corner in viewport pixels. */
	x: number;
	y: number;
}

export interface Size {
	width: number;
	height: number;
}

export interface Viewport {
	width: number;
	height: number;
}

/**
 * What a pane of each subject measures, in pixels.
 *
 * Read by the component into custom properties as well as by the placement
 * below, so the rectangle that is clamped is the rectangle that is drawn. A
 * pane taller than its measure scrolls inside; it does not grow.
 */
export const MEASURE: Record<Subject, Size> = {
	unit: { width: 384, height: 520 },
	rule: { width: 320, height: 300 }
};

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
	return clamped(corner.x, corner.y, size, viewport);
}

/**
 * Open a pane, or raise the one already reading that entry.
 *
 * A rule opened twice from two datasheets is one pane, because two copies of
 * the same text is not two pieces of information.
 */
export function opened(
	open: Pane[],
	wanted: { id: number; subject: Subject; slug: string; title: string },
	size: Size,
	viewport: Viewport,
	from?: Pane
): Pane[] {
	const already = open.find((pane) => pane.subject === wanted.subject && pane.slug === wanted.slug);
	if (already) return raised(open, already.id);
	return [...open, { ...wanted, ...spot(open, size, viewport, from) }];
}

/** Bring a pane to the front; the last of the list is the topmost. */
export function raised(open: Pane[], id: number): Pane[] {
	const pane = open.find((each) => each.id === id);
	if (!pane || open[open.length - 1]?.id === id) return open;
	return [...open.filter((each) => each.id !== id), pane];
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
