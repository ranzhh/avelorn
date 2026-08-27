import type { UnitSummary } from './api/client';

/** The columns a datasheet listing can be ordered by. */
export type Column = 'name' | 'points' | 'troop_type' | 'size' | 'armies';

export interface Order {
	column: Column;
	descending: boolean;
}

/** The minimum models a datasheet may be fielded at. */
export const minimum = (unit: UnitSummary): number => unit.unit_size.min;

/**
 * What the smallest legal unit of this datasheet costs.
 *
 * `points` is per model, and a bare per-model figure says nothing about what
 * taking the unit costs: 8 points is 40 for the five Elven Spearmen you must
 * take to field any at all.
 */
export const fielded = (unit: UnitSummary): number => unit.points * unit.unit_size.min;

/**
 * The sizes a datasheet may be fielded at: `5+`, `3–5`, or a bare `1`.
 *
 * Takes the range rather than the unit so the datasheet route's `Unit` and a
 * listing's `UnitSummary` print it the same way.
 */
export const sizeRange = (size: { min: number; max?: number | null }): string => {
	if (size.max == null) return `${size.min}+`;
	return size.max === size.min ? `${size.min}` : `${size.min}–${size.max}`;
};

/**
 * Whether a datasheet answers to `needle`.
 *
 * One box over everything a listing shows, so a term is not silently scoped to
 * the name: the troop type and the armies fielding it match too.
 */
export function matches(unit: UnitSummary, needle: string): boolean {
	const term = needle.trim().toLowerCase();
	if (!term) return true;
	return [unit.name, unit.troop_type, ...unit.armies].some((field) =>
		field.toLowerCase().includes(term)
	);
}

function key(unit: UnitSummary, column: Column): string | number {
	switch (column) {
		case 'points':
			return fielded(unit);
		case 'size':
			return minimum(unit);
		case 'armies':
			return unit.armies.join(', ');
		case 'troop_type':
			return unit.troop_type;
		case 'name':
			return unit.name;
	}
}

/**
 * The listing, filtered and ordered.
 *
 * Ties break on name so the order is total: two datasheets at the same points
 * would otherwise swap places between renders.
 */
export function listing(units: UnitSummary[], needle: string, order: Order): UnitSummary[] {
	const direction = order.descending ? -1 : 1;
	return units
		.filter((unit) => matches(unit, needle))
		.sort((one, two) => {
			const a = key(one, order.column);
			const b = key(two, order.column);
			const cmp =
				typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b));
			return cmp === 0 ? one.name.localeCompare(two.name) : cmp * direction;
		});
}

/** The order after clicking a column heading: same column reverses, a new one starts ascending. */
export function reorder(current: Order, column: Column): Order {
	return { column, descending: current.column === column ? !current.descending : false };
}
