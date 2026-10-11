import type { FightLanes, LaneUnit, Needed, Strike } from '$lib/api/client';
import { percent } from '$lib/charts/scale';

/** A lane of the drawing: the charger's above, its target's below. */
export type Lane = 'attacker' | 'target';
export const LANES: Lane[] = ['attacker', 'target'];

export type Font = 'title' | 'text' | 'small' | 'mono' | 'chip';
/** How wide a run of text is drawn in one of the drawing's fonts, in pixels. */
export type Measure = (text: string, font: Font) => number;

export interface Point {
	x: number;
	y: number;
}

export interface Box extends Point {
	width: number;
	height: number;
}

/** Where text and controls sit inside a card, from its top left corner. */
export const INSET = 14;
export const UNIT = {
	least: 184,
	chips: 34,
	chip: 20,
	gap: 4,
	glyph: 14,
	pitch: 17,
	packed: 15,
	bottom: 14
};
export const STRIKE = { least: 150, inset: 12, header: 26, rule: 92, row: 20 };
const CHARGE = { width: 170, height: 76 };
const RESULT = { least: 150, height: 128 };
const BREAK = { width: 190, height: 56 };
const PILL = { least: 50, height: 26 };

/** The letter drawn in the square of a command model of each kind. */
export const MARK: Record<LaneUnit['command'][number]['kind'], string> = {
	champion: 'C',
	standard_bearer: 'S',
	musician: 'M'
};

export type Share = ['attacker' | 'draw' | 'target', number];

/** One thing drawn on a card, placed from the card's top left corner. */
export type Mark =
	| {
			kind: 'text';
			x: number;
			y: number;
			text: string;
			font: Font;
			anchor: 'start' | 'middle' | 'end';
	  }
	| { kind: 'chip'; box: Box; text: string; held: boolean }
	| { kind: 'model'; box: Box; command: LaneUnit['command'][number] | null }
	| { kind: 'divider'; y: number }
	| { kind: 'shares'; box: Box; shares: Share[] };

/**
 * What a card shows, and how big it is.
 *
 * `chrome` is its outline: a card with a spine in its side's colour, one with
 * a header band holding its title, a plain card, or a pill.
 */
export interface Face {
	chrome: 'spine' | 'header' | 'card' | 'pill';
	width: number;
	height: number;
	marks: Mark[];
}

/** A chip of a unit card: an option the unit bought, or a piece it holds, highlighted. */
export interface Chip extends Box {
	text: string;
	held: boolean;
}

export interface Model<T> {
	file: number;
	rank: number;
	command: T | null;
}

/**
 * A unit's models rank by rank from the front, its command group in the middle
 * of the front rank, and in the middle of the ranks behind where the front is
 * narrower than the group.
 */
export function formation<T>(size: number, frontage: number, command: T[]): Model<T>[] {
	return Array.from({ length: size }, (_, index) => {
		const rank = Math.floor(index / frontage);
		const file = index % frontage;
		const group = command.slice(rank * frontage, (rank + 1) * frontage);
		const first = Math.floor((Math.min(frontage, size - rank * frontage) - group.length) / 2);
		return { file, rank, command: group[file - first] ?? null };
	});
}

/** A count that is usually whole: whole when it is, else to two places. */
export function count(value: number): string {
	const rounded = Math.round(value * 100) / 100;
	return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

export const mean = (value: number): string => value.toFixed(2);

/** The scores the rolls need, on two lines: To Hit and To Wound, then the saves. */
export function needs(needed: Needed): [string, string] {
	const rolls = [
		needed.hit !== null && `hit ${needed.hit}`,
		needed.wound && `wound ${needed.wound}`
	];
	const saves = [
		needed.save === '-' ? 'no save' : needed.save && `save ${needed.save}`,
		needed.ward && needed.ward !== '-' && `ward ${needed.ward}`
	];
	const line = (parts: (string | false | null)[]) => parts.filter(Boolean).join('  ');
	return [line(rolls), line(saves)];
}

export function partRow(part: Strike['parts'][number]): [string, string] {
	const many = count(part.models.mean) !== '1' ? ` ×${count(part.models.mean)}` : '';
	return [`${part.name}${many}`, `${count(part.attacks.mean)} att → ${mean(part.unsaved.mean)}`];
}

/** Who strikes: a lone part by name, else the unit, with a row for each part. */
export function striker(strike: Strike, unit: string): { title: string; rows: [string, string][] } {
	const rows = strike.parts.map(partRow);
	return rows.length === 1 ? { title: rows[0][0], rows: [] } : { title: unit, rows };
}

const text = (
	x: number,
	y: number,
	value: string,
	font: Font,
	anchor: 'start' | 'middle' | 'end' = 'start'
): Mark => ({ kind: 'text', x, y, text: value, font, anchor });

/** A unit's card, at least `least` wide so both units' cards can match. */
export function unitFace(unit: LaneUnit, measure: Measure, least = UNIT.least): Face {
	const dims = measure(`${unit.frontage} × ${unit.ranks}`, 'mono');
	const chipped = [
		...unit.options.map((option) => ({ text: option.name, held: false })),
		...unit.held.map((held) => ({ text: held, held: true }))
	];
	const chipWidths = chipped.map((chip) => measure(chip.text, 'chip') + 18);
	const width = Math.max(
		least,
		2 * INSET + measure(unit.name, 'title') + 12 + measure(`×${unit.size}`, 'mono'),
		2 * INSET + Math.max(...chipWidths),
		2 * INSET + unit.frontage * UNIT.packed + 12 + dims
	);
	const marks: Mark[] = [
		text(INSET, 23, unit.name, 'title'),
		text(width - INSET, 23, `×${unit.size}`, 'mono', 'end')
	];
	let x = INSET;
	let y = UNIT.chips;
	chipped.forEach((chip, index) => {
		if (x > INSET && x + chipWidths[index] > width - INSET) {
			x = INSET;
			y += UNIT.chip + UNIT.gap;
		}
		const box = { x, y, width: chipWidths[index], height: UNIT.chip };
		marks.push({ kind: 'chip', box, ...chip });
		x += chipWidths[index] + UNIT.gap;
	});
	const pitch = Math.min(UNIT.pitch, Math.floor((width - 2 * INSET - dims - 12) / unit.frontage));
	const top = y + UNIT.chip + UNIT.glyph;
	const ranks = Math.ceil(unit.size / unit.frontage);
	for (const model of formation(unit.size, unit.frontage, unit.command)) {
		const box = {
			x: INSET + model.file * pitch,
			y: top + model.rank * pitch,
			width: pitch - 3,
			height: pitch - 3
		};
		marks.push({ kind: 'model', box, command: model.command });
	}
	marks.push(
		text(width - INSET, top + ranks * pitch - 5, `${unit.frontage} × ${unit.ranks}`, 'mono', 'end')
	);
	return { chrome: 'spine', width, height: top + ranks * pitch + UNIT.bottom, marks };
}

export function chargeFace(charge: NonNullable<FightLanes['charge']>): Face {
	return {
		chrome: 'spine',
		...CHARGE,
		marks: [
			text(INSET, 23, 'Charge', 'title'),
			text(INSET, 43, `${charge.distance}in · ${charge.arc}`, 'mono'),
			text(INSET, 61, `roll ≥ ${charge.distance}in`, 'mono')
		]
	};
}

function headed(
	title: string,
	first: string,
	needed: Needed,
	rows: [string, string][],
	measure: Measure
): Face {
	const lines = needs(needed);
	const pad = 2 * STRIKE.inset;
	const width = Math.max(
		STRIKE.least,
		pad + measure(title, 'title'),
		...lines.map((line) => pad + measure(line, 'mono')),
		...rows.map(
			([name, figures]) => pad + measure(name, 'text') + STRIKE.inset + measure(figures, 'mono')
		)
	);
	const marks: Mark[] = [
		text(STRIKE.inset, 18, title, 'title'),
		text(STRIKE.inset, 46, first, 'text'),
		text(STRIKE.inset, 65, lines[0], 'mono'),
		text(STRIKE.inset, 82, lines[1], 'mono')
	];
	if (rows.length) marks.push({ kind: 'divider', y: STRIKE.rule });
	rows.forEach(([name, figures], index) => {
		const y = STRIKE.rule + 18 + index * STRIKE.row;
		marks.push(
			text(STRIKE.inset, y, name, 'text'),
			text(width - STRIKE.inset, y, figures, 'mono', 'end')
		);
	});
	const height = rows.length ? STRIKE.rule + rows.length * STRIKE.row + 12 : STRIKE.rule;
	return { chrome: 'header', width, height, marks };
}

export function volleyFace(
	volley: NonNullable<FightLanes['volley']>,
	shooter: string,
	measure: Measure
) {
	return headed(shooter, `${volley.shots} shots`, volley.needed, [], measure);
}

export function strikeFace(strike: Strike, unit: string, measure: Measure): Face {
	const { title, rows } = striker(strike, unit);
	return headed(title, `${count(strike.attacks.mean)} attacks`, strike.needed, rows, measure);
}

/** A lane's models standing: the count it fielded at the start, the mean after. */
export function pillFace(models: number, start: boolean, measure: Measure): Face {
	const shown = start ? String(models) : mean(models);
	const width = Math.max(PILL.least, measure(shown, 'mono') + 24);
	return {
		chrome: 'pill',
		width,
		height: PILL.height,
		marks: [text(width / 2, 17, shown, 'mono', 'middle')]
	};
}

export function resultFace(lanes: FightLanes, measure: Measure): Face {
	const { result } = lanes;
	const shares: Share[] = [
		['attacker', result.attacker_wins],
		['draw', result.draw],
		['target', result.target_wins]
	];
	const width = Math.max(
		RESULT.least,
		...LANES.map(
			(lane) =>
				3 * STRIKE.inset +
				measure(lanes.units[lane].name, 'text') +
				measure(mean(result.scores[lane].score.mean), 'mono')
		),
		2 * STRIKE.inset + 3 * (18 + Math.max(...shares.map(([, p]) => measure(percent(p), 'mono'))))
	);
	const marks: Mark[] = [text(STRIKE.inset, 23, 'Combat result', 'title')];
	LANES.forEach((lane, index) => {
		const y = 45 + index * 19;
		marks.push(
			text(STRIKE.inset, y, lanes.units[lane].name, 'text'),
			text(width - STRIKE.inset, y, mean(result.scores[lane].score.mean), 'mono', 'end')
		);
	});
	const box = { x: STRIKE.inset, y: 78, width: width - 2 * STRIKE.inset, height: 12 };
	marks.push({ kind: 'shares', box, shares });
	return { chrome: 'card', width, height: RESULT.height, marks };
}

export function breakFace(test: FightLanes['breaks']['attacker']): Face {
	return {
		chrome: 'spine',
		...BREAK,
		marks: [
			text(INSET, 22, 'Break test', 'title'),
			text(INSET, 43, `Ld ${test.leadership ?? '–'}`, 'mono')
		]
	};
}
