import type { FightLanes, LandedRule, LaneUnit, Needed, Spread, Strike } from '$lib/api/client';
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
export const STRIKE = { least: 150, inset: 12, header: 26, row: 18 };
const CHARGE = { width: 170, height: 55 };
const RESULT = { least: 150, height: 128 };
const BREAK = { width: 190, height: 56 };
const PILL = { least: 50, height: 26 };
const RULE = { row: 20, box: 11, side: 8 };
/** A chart of a count's chances, and how wide a card must be to draw one. */
const CHART = { height: 80, least: 220 };

/** The letter drawn in the square of a command model of each kind. */
export const MARK: Record<LaneUnit['command'][number]['kind'], string> = {
	champion: 'C',
	standard_bearer: 'S',
	musician: 'M'
};

export type Share = ['attacker' | 'draw' | 'target', number];
/** A colour a chart's bars take: a side's, a draw's, or grey short of a rule. */
export type Tone = Lane | 'draw' | 'short';
/** A colour of a chart's bars and its chance of each outcome, the layers stacked from the bottom. */
export type Layer = [Tone, number[]];

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
	| { kind: 'rule'; x: number; y: number; rule: LandedRule }
	| {
			kind: 'chart';
			name: string;
			box: Box;
			spread: Spread;
			layers: Layer[];
			/** An outcome a rule is drawn before. */
			rule: number | null;
	  }
	| { kind: 'meter'; box: Box; p: number };

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

/** A count over every outcome: plain when it cannot vary, else its mean ± its standard deviation. */
export function spread({ mean, sd }: Pick<Spread, 'mean' | 'sd'>): string {
	if (sd === 0) return count(mean);
	const figure = (value: number) => value.toFixed(Math.abs(value) < 1 ? 2 : 1);
	return `${figure(mean)} ± ${figure(sd)}`;
}

/** A part of a strike by name, with how many strike where that is not always one. */
function part({ name, models }: Strike['parts'][number]): string {
	return models.sd === 0 && models.mean === 1 ? name : `${name} ×${spread(models)}`;
}

/** Who strikes: a lone part, else the unit. */
export function striker(strike: Strike, unit: string): string {
	return strike.parts.length === 1 ? part(strike.parts[0]) : unit;
}

/** A count's chances in its side's colour, greyed short of `rule`. */
function toned({ least, distribution }: Spread, lane: Lane, rule: number | null = null): Layer[] {
	if (rule === null) return [[lane, distribution]];
	const short = (k: number) => least + k < rule;
	return [
		['short', distribution.map((p, k) => (short(k) ? p : 0))],
		[lane, distribution.map((p, k) => (short(k) ? 0 : p))]
	];
}

const chart = (
	name: string,
	box: Box,
	counted: Spread,
	layers: Layer[],
	rule: number | null = null
): Mark => ({ kind: 'chart', name, box, spread: counted, layers, rule });

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

/** The maximum possible charge range term by term, and its sum. */
function maximum(terms: NonNullable<FightLanes['charge']>['maximum']): string {
	const named = terms.map(({ name, inches }) => (name ? `${name} ${inches}` : String(inches)));
	return `${named.join(' + ')} = ${terms.reduce((sum, { inches }) => sum + inches, 0)}in`;
}

/** The charge: shut, the chance it reaches; open, the range its roll can give and its chances. */
export function chargeFace(
	charge: NonNullable<FightLanes['charge']>,
	measure: Measure,
	open: boolean
): Face {
	const rules = open ? charge.rules : [];
	const reaches = percent(charge.reaches);
	const sum = maximum(charge.maximum);
	const furthest = `${charge.furthest}in`;
	const width = Math.max(
		CHARGE.width,
		ruleWidth(rules, INSET, measure),
		2 * INSET + measure('Charge', 'title') + 12 + measure(reaches, 'mono'),
		open ? CHART.least : 0,
		open ? 2 * INSET + measure('maximum', 'small') + 12 + measure(sum, 'mono') : 0
	);
	const marks: Mark[] = [
		text(INSET, 23, 'Charge', 'title'),
		text(width - INSET, 23, reaches, 'mono', 'end'),
		{
			kind: 'meter',
			box: { x: INSET, y: 33, width: width - 2 * INSET, height: 8 },
			p: charge.reaches
		}
	];
	let height = CHARGE.height;
	if (open) {
		const box = { x: INSET, y: 114, width: width - 2 * INSET, height: CHART.height };
		marks.push(
			text(INSET, 64, 'maximum', 'small'),
			text(width - INSET, 64, sum, 'mono', 'end'),
			text(INSET, 83, 'furthest', 'small'),
			text(width - INSET, 83, furthest, 'mono', 'end'),
			text(INSET, 103, 'range', 'small'),
			chart(
				'range',
				box,
				charge.range,
				toned(charge.range, 'attacker', charge.distance),
				charge.distance
			)
		);
		height = box.y + box.height + 12;
	}
	return ruled({ chrome: 'spine', width, height, marks }, rules, INSET);
}

/** Figures in columns under their heads, each row named. */
interface Table {
	heads: string[];
	rows: [string, ...string[]][];
}

function tableWidth({ heads, rows }: Table, measure: Measure): number {
	const name = Math.max(...rows.map(([first]) => measure(first, 'text')));
	const columns = heads.map((head, index) =>
		Math.max(measure(head, 'small'), ...rows.map((row) => measure(row[index + 1], 'mono')))
	);
	return name + columns.reduce((sum, column) => sum + 16 + column, 0);
}

/** The table's marks from `y` down, and the baseline of its last row. */
function tabled({ heads, rows }: Table, width: number, y: number, measure: Measure) {
	const marks: Mark[] = [];
	let right = width - STRIKE.inset;
	for (let index = heads.length - 1; index >= 0; index -= 1) {
		const values = rows.map((row) => row[index + 1]);
		marks.push(text(right, y, heads[index], 'small', 'end'));
		values.forEach((value, at) =>
			marks.push(text(right, y + (at + 1) * STRIKE.row, value, 'mono', 'end'))
		);
		const column = Math.max(
			measure(heads[index], 'small'),
			...values.map((value) => measure(value, 'mono'))
		);
		right -= column + 16;
	}
	rows.forEach(([name], at) =>
		marks.push(text(STRIKE.inset, y + (at + 1) * STRIKE.row, name, 'text'))
	);
	return { marks, last: y + rows.length * STRIKE.row };
}

/** What a header card shows open: its parts, the chances of its counts, the rules on it. */
interface Opened {
	table: Table | null;
	charts: [string, Spread][];
	rules: LandedRule[];
}

/** A card under a header band: four lines shut, and its parts, charts and rules open. */
function headed(
	title: string,
	lines: [string, string, string, string],
	tone: Lane,
	opened: Opened | null,
	measure: Measure
): Face {
	const pad = 2 * STRIKE.inset;
	const rules = opened?.rules ?? [];
	const table = opened?.table ?? null;
	const width = Math.max(
		STRIKE.least,
		opened ? CHART.least : 0,
		ruleWidth(rules, STRIKE.inset, measure),
		table ? pad + tableWidth(table, measure) : 0,
		pad + measure(title, 'title'),
		...lines.map((line, index) => pad + measure(line, index % 3 ? 'mono' : 'text'))
	);
	const marks: Mark[] = [
		text(STRIKE.inset, 18, title, 'title'),
		...lines.map((line, index) =>
			text(STRIKE.inset, 46 + index * 19, line, index % 3 ? 'mono' : 'text')
		)
	];
	let y = 46 + 3 * 19 + 13;
	if (opened) {
		y -= 4;
		marks.push({ kind: 'divider', y });
		if (table) {
			const placed = tabled(table, width, y + 16, measure);
			marks.push(...placed.marks);
			y = placed.last + 6;
		}
		for (const [name, counted] of opened.charts) {
			marks.push(text(STRIKE.inset, y + 15, name, 'small'));
			const box = { x: STRIKE.inset, y: y + 26, width: width - pad, height: CHART.height };
			marks.push(chart(name, box, counted, toned(counted, tone)));
			y = box.y + box.height;
		}
		y += 12;
	}
	return ruled({ chrome: 'header', width, height: y, marks }, rules, STRIKE.inset);
}

export function volleyFace(
	volley: NonNullable<FightLanes['volley']>,
	shooter: string,
	measure: Measure,
	open: boolean
): Face {
	const [rolls, saves] = needs(volley.needed);
	const lines = [
		`${volley.shots} shots`,
		rolls,
		saves,
		`${spread(volley.casualties)} casualties`
	] as const;
	const opened = open && {
		table: {
			heads: ['shots', 'unsaved'],
			rows: volley.parts.map((part): [string, ...string[]] => [
				part.name,
				String(part.shots),
				spread(part.unsaved)
			])
		},
		charts: [['casualties', volley.casualties]] as [string, Spread][],
		rules: volley.rules
	};
	return headed(shooter, [...lines], 'target', opened || null, measure);
}

export function strikeFace(strike: Strike, unit: string, measure: Measure, open: boolean): Face {
	const [rolls, saves] = needs(strike.needed);
	const lines = [
		`${spread(strike.attacks)} attacks`,
		rolls,
		saves,
		`${spread(strike.unsaved)} unsaved`
	] as const;
	const charts: [string, Spread][] = [['unsaved', strike.unsaved]];
	if (strike.attacks.sd > 0) charts.push(['attacks', strike.attacks]);
	const opened = open && {
		table:
			strike.parts.length > 1
				? {
						heads: ['attacks', 'unsaved'],
						rows: strike.parts.map((each): [string, ...string[]] => [
							part(each),
							spread(each.attacks),
							spread(each.unsaved)
						])
					}
				: null,
		charts,
		rules: strike.rules
	};
	const title = striker(strike, unit);
	return headed(title, [...lines], strike.side as Lane, opened || null, measure);
}

/** A lane's models standing: shut, a pill of the count; open, a card charting its chances. */
export function pillFace(models: Spread, lane: Lane, measure: Measure, open: boolean): Face {
	const shown = spread(models);
	if (!open) {
		const width = Math.max(PILL.least, measure(shown, 'mono') + 24);
		return {
			chrome: 'pill',
			width,
			height: PILL.height,
			marks: [text(width / 2, 17, shown, 'mono', 'middle')]
		};
	}
	const width = Math.max(CHART.least, 3 * STRIKE.inset + measure(shown, 'mono') + 40);
	const box = { x: STRIKE.inset, y: 34, width: width - 2 * STRIKE.inset, height: CHART.height };
	return {
		chrome: 'card',
		width,
		height: box.y + box.height + 12,
		marks: [
			text(STRIKE.inset, 20, 'models', 'small'),
			text(width - STRIKE.inset, 20, shown, 'mono', 'end'),
			chart('models', box, models, toned(models, lane))
		]
	};
}

/** A side's combat result in its parts: each a name and its count, the Wounds charted. */
function scoring(lanes: FightLanes, lane: Lane): [string, string][] {
	const scored = lanes.result.scores[lane];
	return [
		[lanes.units[lane].name, spread(scored.score)],
		['Wounds', spread(scored.wounds)],
		['Rank Bonus', spread(scored.rank_bonus)],
		['Flank or Rear', spread(scored.flank_or_rear)],
		...scored.rules.map((rule): [string, string] => [rule.name, spread(rule.points)])
	];
}

/** The combat result: shut, each side's score and how the round goes; open, the scores in parts. */
export function resultFace(lanes: FightLanes, measure: Measure, open: boolean): Face {
	const { result } = lanes;
	const rules = open ? result.rules : [];
	const shares: Share[] = [
		['attacker', result.attacker_wins],
		['draw', result.draw],
		['target', result.target_wins]
	];
	const pad = 2 * STRIKE.inset;
	const parts = { attacker: scoring(lanes, 'attacker'), target: scoring(lanes, 'target') };
	const row = ([name, value]: [string, string], index: number) =>
		measure(name, index ? 'small' : 'text') + 12 + measure(value, 'mono');
	const column = open
		? Math.max(CHART.least / 2 + 40, ...LANES.flatMap((lane) => parts[lane].map(row)))
		: 0;
	const width = Math.max(
		RESULT.least,
		ruleWidth(rules, STRIKE.inset, measure),
		open ? pad + 2 * column + 16 : 0,
		...LANES.map((lane) => pad + STRIKE.inset + row(parts[lane][0], 0)),
		pad + 3 * (18 + Math.max(...shares.map(([, p]) => measure(percent(p), 'mono'))))
	);
	const marks: Mark[] = [text(STRIKE.inset, 23, 'Combat result', 'title')];
	let y = 78;
	if (open) {
		const wide = (width - pad - 16) / 2;
		let bottom = 0;
		LANES.forEach((lane, index) => {
			const x = STRIKE.inset + index * (wide + 16);
			const [[name, score], [wounds, inflicted], ...rest] = parts[lane];
			const box = { x, y: 76, width: wide, height: 64 };
			marks.push(
				text(x, 45, name, 'text'),
				text(x + wide, 45, score, 'mono', 'end'),
				text(x, 64, wounds, 'small'),
				text(x + wide, 64, inflicted, 'mono', 'end'),
				chart(wounds, box, result.scores[lane].wounds, toned(result.scores[lane].wounds, lane)),
				...rest.flatMap(([part, value], at) => [
					text(x, 158 + at * 19, part, 'small'),
					text(x + wide, 158 + at * 19, value, 'mono', 'end')
				])
			);
			bottom = Math.max(bottom, 158 + (rest.length - 1) * 19);
		});
		const box = { x: STRIKE.inset, y: bottom + 30, width: width - pad, height: CHART.height };
		const { winners } = result;
		marks.push(
			text(STRIKE.inset, bottom + 19, 'margin', 'small'),
			chart('margin', box, result.margin, [
				['attacker', winners.attacker_wins],
				['draw', winners.draw],
				['target', winners.target_wins]
			])
		);
		y = box.y + box.height + 14;
	} else {
		LANES.forEach((lane, index) => {
			const [name, score] = parts[lane][0];
			marks.push(
				text(STRIKE.inset, 45 + index * 19, name, 'text'),
				text(width - STRIKE.inset, 45 + index * 19, score, 'mono', 'end')
			);
		});
	}
	const box = { x: STRIKE.inset, y, width: width - pad, height: 12 };
	marks.push({ kind: 'shares', box, shares });
	const face: Face = { chrome: 'card', width, height: y + RESULT.height - 78, marks };
	return ruled(face, rules, STRIKE.inset);
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
