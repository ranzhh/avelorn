import type { ChosenOption, UnitOption } from './api/client';

/** What an option costs, as a datasheet prints it. */
export function cost(option: UnitOption): string {
	if (option.points_budget) return `up to ${option.points_budget} pts`;
	if (!option.points) return '';
	return `${option.points} pts${option.per_model ? '/model' : ''}`;
}

/**
 * The options a block saved by printed name bought.
 *
 * A block picked by name bought every option printing that name, so a name
 * Dwarf Warriors print twice reads back as both.
 */
export function byName(offered: UnitOption[], names: string[]): ChosenOption[] {
	return offered
		.filter((option) => names.includes(option.name))
		.map(({ id, name }) => ({ id, name }));
}
