import type { UnitOption } from './api/client';

/** What an option costs, as a datasheet prints it. */
export function cost(option: UnitOption): string {
	if (option.points_budget) return `up to ${option.points_budget} pts`;
	if (!option.points) return '';
	return `${option.points} pts${option.per_model ? '/model' : ''}`;
}

/**
 * Whether a datasheet prints this option's name more than once.
 *
 * Dwarf Warriors offer a Veteran champion and a Veteran special rule, and a
 * complement picks options by name, so ticking either buys both.
 */
export function repeated(offered: UnitOption[], name: string): boolean {
	return offered.filter((option) => option.name === name).length > 1;
}
