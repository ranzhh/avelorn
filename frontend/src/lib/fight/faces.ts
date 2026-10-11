import type { FightLanes, LandedRule, LaneUnit, Needed, Strike } from '$lib/api/client';
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
export const UNIT = { least: 184, editor: 248, chips: 34, chip: 20, gap: 4, bottom: 14 };
/** Pixels to the millimetre: a formation stands on its bases at this scale. */
const SCALE = 0.6;
export const STRIKE = { least: 150, inset: 12, header: 26, rule: 92, row: 20 };
const CHARGE = { width: 170, height: 76 };
const RESULT = { least: 150, height: 128 };
const BREAK = { width: 190, height: 56 };
const PILL = { least: 50, height: 26 };
const RULE = { row: 20, box: 11, side: 8 };

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
	| { kind: 'shares'; box: Box; shares: Share[] }
	| { kind: 'rule'; x: number; y: number; rule: LandedRule };

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
	/** Room on the card for controls drawn over it. */
	slot?: Box;
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

/** How wide a card must be to list `rules`: a checkbox, the rule's name, its side's colour. */
function ruleWidth(rules: LandedRule[], inset: number, measure: Measure): number {
	const widths = rules.map((rule) => measure(rule.name, 'text'));
	return Math.max(0, ...widths.map((width) => 2 * inset + RULE.box + 7 + width + 12 + RULE.side));
}

/** The face with the rules landing on it listed under it, each ticked where it applied. */
function ruled(face: Face, rules: LandedRule[], inset: number): Face {
	if (!rules.length) return face;
	const top = face.height - 4;
	const listed = rules.map((rule, index): Mark => ({
		kind: 'rule',
		x: inset,
		y: top + 19 + index * RULE.row,
		rule
	}));
	return {
		...face,
		height: top + rules.length * RULE.row + 8,
		marks: [...face.marks, { kind: 'divider', y: top }, ...listed]
	};
}

/** The face with room under it for controls `height` tall, as it is with none. */
function editable(face: Face, height: number | null): Face {
	if (height === null) return face;
	const top = face.height - 4;
	const slot = { x: INSET, y: top + 12, width: face.width - 2 * INSET, height };
	return {
		...face,
		height: slot.y + height + 12,
		marks: [...face.marks, { kind: 'divider', y: top }],
		slot
	};
}

/**
 * A unit's card, at least `least` wide so both units' cards can match, with
 * room for an editor `editor` tall when it is edited in place.
 */
export function unitFace(
	unit: LaneUnit,
	measure: Measure,
	open: boolean,
	least = 0,
	editor: number | null = null
): Face {
	const rules = open ? unit.rules : [];
	const strength = String(unit.unit_strength);
	const chipped = [
		...unit.options.map((option) => ({ text: option.name, held: false })),
		...unit.held.map((held) => ({ text: held, held: true }))
	];
	const chipWidths = chipped.map((chip) => measure(chip.text, 'chip') + 18);
	const base = unit.base && {
		width: unit.base.width_mm * SCALE,
		depth: unit.base.depth_mm * SCALE
	};
	const width = Math.max(
		UNIT.least,
		least,
		editor === null ? 0 : 2 * INSET + UNIT.editor,
		ruleWidth(rules, INSET, measure),
		2 * INSET + measure(unit.name, 'title') + 12 + measure(`×${unit.size}`, 'mono'),
		2 * INSET + Math.max(...chipWidths),
		2 * INSET + unit.frontage * (base?.width ?? 0),
		2 * INSET + measure('Unit Strength', 'small') + 12 + measure(strength, 'mono')
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
	let bottom = chipped.length ? y + UNIT.chip : y - UNIT.gap;
	if (base) {
		const top = bottom + UNIT.gap + 8;
		for (const model of formation(unit.size, unit.frontage, unit.command)) {
			const box = {
				x: INSET + model.file * base.width,
				y: top + model.rank * base.depth,
				width: base.width,
				height: base.depth
			};
			marks.push({ kind: 'model', box, command: model.command });
		}
		bottom = top + Math.ceil(unit.size / unit.frontage) * base.depth;
	}
	marks.push(
		text(INSET, bottom + 20, 'Unit Strength', 'small'),
		text(width - INSET, bottom + 20, strength, 'mono', 'end')
	);
	const face: Face = { chrome: 'spine', width, height: bottom + 20 + UNIT.bottom, marks };
	return editable(ruled(face, rules, INSET), editor);
}

export function chargeFace(
	charge: NonNullable<FightLanes['charge']>,
	measure: Measure,
	open: boolean
): Face {
	const rules = open ? charge.rules : [];
	const face: Face = {
		chrome: 'spine',
		width: Math.max(CHARGE.width, ruleWidth(rules, INSET, measure)),
		height: CHARGE.height,
		marks: [
			text(INSET, 23, 'Charge', 'title'),
			text(INSET, 43, `${charge.distance}in · ${charge.arc}`, 'mono'),
			text(INSET, 61, `roll ≥ ${charge.distance}in`, 'mono')
		]
	};
	return ruled(face, rules, INSET);
}

function headed(
	title: string,
	first: string,
	needed: Needed,
	rows: [string, string][],
	rules: LandedRule[],
	measure: Measure
): Face {
	const lines = needs(needed);
	const pad = 2 * STRIKE.inset;
	const width = Math.max(
		STRIKE.least,
		ruleWidth(rules, STRIKE.inset, measure),
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
	return ruled({ chrome: 'header', width, height, marks }, rules, STRIKE.inset);
}

export function volleyFace(
	volley: NonNullable<FightLanes['volley']>,
	shooter: string,
	measure: Measure,
	open: boolean
): Face {
	const rules = open ? volley.rules : [];
	return headed(shooter, `${volley.shots} shots`, volley.needed, [], rules, measure);
}

export function strikeFace(strike: Strike, unit: string, measure: Measure, open: boolean): Face {
	const { title, rows } = striker(strike, unit);
	const attacks = `${count(strike.attacks.mean)} attacks`;
	return headed(title, attacks, strike.needed, rows, open ? strike.rules : [], measure);
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

export function resultFace(lanes: FightLanes, measure: Measure, open: boolean): Face {
	const { result } = lanes;
	const rules = open ? result.rules : [];
	const shares: Share[] = [
		['attacker', result.attacker_wins],
		['draw', result.draw],
		['target', result.target_wins]
	];
	const width = Math.max(
		RESULT.least,
		ruleWidth(rules, STRIKE.inset, measure),
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
	return ruled({ chrome: 'card', width, height: RESULT.height, marks }, rules, STRIKE.inset);
}

export function breakFace(
	test: FightLanes['breaks']['attacker'],
	measure: Measure,
	open: boolean
): Face {
	const rules = open ? test.rules : [];
	const face: Face = {
		chrome: 'spine',
		width: Math.max(BREAK.width, ruleWidth(rules, INSET, measure)),
		height: BREAK.height,
		marks: [
			text(INSET, 22, 'Break test', 'title'),
			text(INSET, 43, `Ld ${test.leadership ?? '–'}`, 'mono')
		]
	};
	return ruled(face, rules, INSET);
}
