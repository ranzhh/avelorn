/**
 * The matrix of every standing block against every other.
 *
 * One fight answers one question. A list is not one question -- it is whether
 * the thing you paid 2000 points for beats what is across the table, and that
 * is a grid rather than a number. This is the arithmetic behind the grid: which
 * pairs to resolve, when the answers go stale, and how strongly a cell leans.
 */

import type { Placed } from './table';

/** How a round is posed. A charge is worth up to +3 Initiative into the front. */
export type Stance = 'engaged' | 'charged';

/** The distance that caps the front-arc charge bonus, so a charged row gets all of it. */
export const FULL_CHARGE = 3;

export interface Pairing {
	row: number;
	column: number;
}

/**
 * Every ordered pair of distinct blocks.
 *
 * Ordered, not combinations: A charging B is not B charging A, and even at rest
 * the row is the side whose win the cell reports.
 */
export function pairings(count: number): Pairing[] {
	const out: Pairing[] = [];
	for (let row = 0; row < count; row += 1) {
		for (let column = 0; column < count; column += 1) {
			if (row !== column) out.push({ row, column });
		}
	}
	return out;
}

/**
 * What the matrix depends on.
 *
 * A fight reads each side's datasheet, size, options and weapon. It does not
 * read where the block stands, so dragging one across the table leaves every
 * answer good. Moving a block is the common action; re-resolving the grid for
 * it would be the common waste.
 */
export function roster(placed: Placed[], stance: Stance): string {
	const each = placed.map(
		(block) =>
			`${block.block.unit}:${block.block.size}:${block.block.options.join('+')}:${block.melee}`
	);
	return `${stance}|${each.join('|')}`;
}

/**
 * A cell's fill, leaning to the pole of whoever is winning.
 *
 * `--neutral` is the diverging midpoint the tokens declare, so an even matchup
 * is the plain midpoint and a decided one is nearly a pole. The lean stops
 * short of the pole itself, because the number sits on top of this and has to
 * stay readable.
 */
export function shade(p: number): string {
	const lean = Math.min(1, Math.abs(p - 0.5) * 2);
	const pole = p >= 0.5 ? '--series-1' : '--series-2';
	return `color-mix(in oklab, var(${pole}) ${Math.round(lean * 62)}%, var(--neutral))`;
}

/**
 * The blocks a row beats, most decisive first.
 *
 * The row's own reading of the grid: what it is for, and what it should not be
 * asked to hold.
 */
export function ranked(wins: (number | null)[]): { column: number; p: number }[] {
	return wins
		.map((p, column) => ({ column, p }))
		.filter((each): each is { column: number; p: number } => each.p !== null)
		.sort((a, b) => b.p - a.p);
}
