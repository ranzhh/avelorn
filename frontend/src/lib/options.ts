import type { ChosenOption, UnitOption } from './api/client';

/** What an option costs, as a datasheet prints it. */
export function cost(option: UnitOption): string {
	if (option.points_budget) return `up to ${option.points_budget} pts`;
	if (!option.points) return '';
	return `${option.points} pts${option.per_model ? '/model' : ''}`;
}

/** The letters some kinds of option always answer to, and the word that shows it where the name lacks it. */
const FIXED: Partial<Record<UnitOption['kind'], [string, string]>> = {
	champion: ['c', 'Champion'],
	standard_bearer: ['s', 'Standard'],
	musician: ['m', 'Musician']
};

/** Kinds that take no key at all: a magic standard is chosen from a list, not ticked. */
const UNKEYED: UnitOption['kind'][] = ['magic_standard'];

/**
 * The key that toggles an option: its letter, and where to underline it.
 *
 * `at` is the letter's place in the option's name, or -1 where the name lacks
 * it and `hint` is printed after the name to carry it.
 */
export interface Key {
	letter: string;
	at: number;
	hint?: string;
}

/**
 * The key that toggles each option.
 *
 * Champion, standard bearer and musician always answer to C, S and M,
 * underlined at the start of a word of the name where one begins with it and on
 * a word after the name where none does. A magic standard takes no key. Every
 * other option takes the first letter of its name nothing else holds; one whose
 * letters are all taken goes without.
 */
export function keys(offered: UnitOption[]): Map<string, Key> {
	const found = new Map<string, Key>();
	const held = new Set<string>();
	for (const option of offered) {
		const fixed = FIXED[option.kind];
		if (!fixed || held.has(fixed[0])) continue;
		const [letter, hint] = fixed;
		const at = option.name.search(new RegExp(`\\b${letter}`, 'i'));
		found.set(option.id, at < 0 ? { letter, at, hint } : { letter, at });
		held.add(letter);
	}
	for (const option of offered) {
		if (found.has(option.id) || UNKEYED.includes(option.kind)) continue;
		const at = [...option.name].findIndex(
			(letter) => /[a-z]/i.test(letter) && !held.has(letter.toLowerCase())
		);
		if (at < 0) continue;
		const letter = option.name[at].toLowerCase();
		held.add(letter);
		found.set(option.id, { letter, at });
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
