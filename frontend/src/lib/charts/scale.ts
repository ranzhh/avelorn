/**
 * The arithmetic behind the charts: what part of a distribution to draw, and
 * where to put the ticks.
 *
 * Kept out of the components because it is the part that can be wrong in a way
 * a screenshot will not show.
 */

/** Anything rarer than this is not worth a column of its own. */
const NEGLIGIBLE = 0.0005;

export interface Band {
	/** The first outcome drawn; the mass at `values[from]`. */
	from: number;
	/** The masses drawn, contiguous from `from`. */
	masses: number[];
}

/**
 * The stretch of a distribution worth drawing.
 *
 * The tail of a casualty distribution is a long run of near-zeroes, and a
 * column per index up to the unit's size is mostly empty. This returns a
 * *contiguous* run rather than the non-negligible entries, because an axis with
 * indices missing from the middle would misstate the shape.
 */
export function band(values: number[]): Band {
	const first = values.findIndex((mass) => mass >= NEGLIGIBLE);
	if (first === -1) return { from: 0, masses: values.length ? [values[0]] : [0] };
	let last = values.length - 1;
	while (last > first && values[last] < NEGLIGIBLE) last -= 1;
	return { from: first, masses: values.slice(first, last + 1) };
}

/**
 * Tick values from zero to at least `max`, on a round step.
 *
 * The step is the smallest of 5/10/20/25/50/100 percent giving no more than
 * `count` gaps, so the axis reads in numbers a person would choose.
 */
export function ticks(max: number, count = 4): number[] {
	const steps = [0.05, 0.1, 0.2, 0.25, 0.5, 1];
	const step = steps.find((candidate) => max / candidate <= count) ?? 1;
	const top = Math.ceil(max / step) * step;
	const out: number[] = [];
	for (let value = 0; value <= top + step / 2; value += step) {
		out.push(Number(value.toFixed(4)));
	}
	return out;
}

/** A probability as a percentage, at the precision the number deserves. */
export function percent(p: number): string {
	if (p === 0) return '0%';
	if (p < 0.001) return '<0.1%';
	if (p >= 0.995 && p < 1) return '>99%';
	return `${(p * 100).toFixed(p < 0.1 ? 1 : 0)}%`;
}

/** A probability to two places: for columns that must line up. */
export function exact(p: number): string {
	return `${(p * 100).toFixed(2)}%`;
}

/**
 * How many x-axis labels to skip so they do not collide.
 *
 * A label per column is unreadable below roughly 28px each, so this thins them
 * to every second or every fifth rather than letting them overlap.
 */
export function labelEvery(columns: number, width: number): number {
	if (columns === 0) return 1;
	const per = width / columns;
	if (per >= 28) return 1;
	if (per >= 14) return 2;
	return Math.ceil(28 / Math.max(per, 1));
}
