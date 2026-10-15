import type { ChosenOption, UnitOption } from './api/client';

/** What an option costs, as a datasheet prints it. */
export function cost(option: UnitOption): string {
	if (option.points_budget) return `up to ${option.points_budget} pts`;
	if (!option.points) return '';
	return `${option.points} pts${option.per_model ? '/model' : ''}`;
}

const COMMAND: UnitOption['kind'][] = ['champion', 'standard_bearer', 'musician'];

/**
 * The letter that toggles each option, as its place in the option's name.
 *
 * Command models choose first, so their keys stay put whatever else is on
 * offer; each option then takes the first letter of its name no earlier option
 * holds. An option whose letters are all taken goes without.
 */
export function keys(offered: UnitOption[]): Map<string, number> {
	const ranked = [
		...offered.filter((option) => COMMAND.includes(option.kind)),
		...offered.filter((option) => !COMMAND.includes(option.kind))
	];
	const held = new Set<string>();
	const found = new Map<string, number>();
	for (const option of ranked) {
		const at = [...option.name].findIndex(
			(letter) => /[a-z]/i.test(letter) && !held.has(letter.toLowerCase())
		);
		if (at < 0) continue;
		held.add(option.name[at].toLowerCase());
		found.set(option.id, at);
	}
	return found;
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
