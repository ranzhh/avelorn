import type { FightLanes, LaneUnit, Needed, Strike } from '$lib/api/client';
import { percent } from '$lib/charts/scale';

/** A lane of the drawing: the charger's above, its target's below. */
export type Lane = 'attacker' | 'target';
export const LANES: Lane[] = ['attacker', 'target'];
export const other = (lane: Lane): Lane => (lane === 'attacker' ? 'target' : 'attacker');

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
export const UNIT = { least: 184, chips: 34, chip: 20, gap: 4, glyph: 14, pitch: 17, bottom: 14 };
export const STRIKE = { least: 150, inset: 12, header: 26, rule: 92, row: 20 };
const BATTLEFIELD = { width: 160, height: 140 };
const CHARGE = { width: 170, height: 76 };
const REACTION = { width: 170, height: 80 };
const SHORT = { width: 120, height: 36 };
const RESULT = { least: 150, height: 128 };
const BREAK = { width: 190, height: 56 };
const PILL = { least: 50, height: 26 };
export const OUTCOME = { width: 200, height: 26, step: 34, inset: 30 };
const GAP = 40;
const WIDE = 54;
const HEAD = 46;
const MIDDLE = 54;
const LEFT = 40;
const OPENING = 24;

/** What one lane holds in one column: its own volley or strike, or a pill of its models standing. */
export type Event =
	{ kind: 'volley' } | { kind: 'strike'; strike: number } | { kind: 'pill'; standing: number };

export interface Column {
	head: string;
	attacker: Event | null;
	target: Event | null;
}

/**
 * The columns after the charge, in the order things happen.
 *
 * Each strike takes a column, with the casualties it inflicts as a pill in the
 * other lane. A lane whose first event is a pill opens on its models at the
 * start, so the pills read as a count going down.
 */
export function columns(lanes: Pick<FightLanes, 'volley' | 'strikes' | 'standing'>): Column[] {
	const after = (lane: Lane, slot: string): Event | null => {
		const standing = lanes.standing[lane].findIndex((each) => each.after === slot);
		return standing < 0 ? null : { kind: 'pill', standing };
	};
	const events: Column[] = [];
	if (lanes.volley) {
		const target: Event = { kind: 'volley' };
		events.push({ head: 'Stand & Shoot', attacker: after('attacker', 'volley'), target });
	}
	lanes.strikes.forEach((strike, index) => {
		const lane = strike.side as Lane;
		const column = { head: strike.label, attacker: null, target: null } as Column;
		column[lane] = { kind: 'strike', strike: index };
		column[other(lane)] = after(other(lane), strike.slot);
		events.push(column);
	});
	const opens = (lane: Lane) => events.find((each) => each[lane])?.[lane]?.kind === 'pill';
	const start: Column = { head: '', attacker: null, target: null };
	for (const lane of LANES) if (opens(lane)) start[lane] = { kind: 'pill', standing: 0 };
	return start.attacker || start.target ? [start, ...events] : events;
}

export interface Chip extends Box {
	text: string;
}

export type Command = 'champion' | 'standard' | 'musician';

export interface Model {
	file: number;
	rank: number;
	command: Command | null;
}

/**
 * A unit's models rank by rank from the front, its command group in the middle
 * of the front rank, and in the middle of the ranks behind where the front is
 * narrower than the group.
 */
export function formation(size: number, frontage: number, command: Command[]): Model[] {
	return Array.from({ length: size }, (_, index) => {
		const rank = Math.floor(index / frontage);
		const file = index % frontage;
		const group = command.slice(rank * frontage, (rank + 1) * frontage);
		const first = Math.floor((Math.min(frontage, size - rank * frontage) - group.length) / 2);
		return { file, rank, command: group[file - first] ?? null };
	});
}

export function commanded(unit: LaneUnit): Command[] {
	const { champion, standard, musician } = unit.command;
	return [
		...(champion ? (['champion'] as const) : []),
		...(standard ? (['standard'] as const) : []),
		...(musician ? (['musician'] as const) : [])
	];
}

export type Placed =
	| {
			kind: 'unit';
			id: string;
			lane: Lane;
			box: Box;
			unit: LaneUnit;
			chips: Chip[];
			/** How far below the card's top its formation starts, and the step between two models. */
			glyph: number;
			pitch: number;
	  }
	| { kind: 'battlefield'; id: string; box: Box }
	| { kind: 'charge'; id: string; box: Box }
	| { kind: 'reaction'; id: string; box: Box }
	| { kind: 'short'; id: string; box: Box }
	| { kind: 'volley'; id: string; lane: Lane; box: Box }
	| {
			kind: 'strike';
			id: string;
			lane: Lane;
			box: Box;
			strike: Strike;
			title: string;
			rows: [string, string][];
	  }
	| { kind: 'pill'; id: string; lane: Lane; box: Box; text: string }
	| { kind: 'result'; id: string; box: Box }
	| { kind: 'break'; id: string; lane: Lane; box: Box }
	| { kind: 'outcome'; id: string; lane: Lane; box: Box; name: string; p: number };

export interface Edge {
	d: string;
	tone?: Lane;
	/** Drawn without an arrowhead: a spine the arrows branch off. */
	bare?: boolean;
}

export interface Label extends Point {
	text: string;
	tone?: Lane;
	anchor: 'start' | 'middle' | 'end';
}

export interface Drawing {
	width: number;
	height: number;
	bands: Record<Lane, Box>;
	heads: { x: number; text: string }[];
	nodes: Placed[];
	edges: Edge[];
	labels: Label[];
}

/** A count that is usually whole: whole when it is, else to two places. */
export function count(value: number): string {
	const rounded = Math.round(value * 100) / 100;
	return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

export const mean = (value: number): string => value.toFixed(2);

export const signed = (value: number): string =>
	`${value < 0 ? '−' : value > 0 ? '+' : ''}${Math.abs(value).toFixed(2)}`;

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
	const many = count(part.models) !== '1' ? ` ×${count(part.models)}` : '';
	return [`${part.name}${many}`, `${count(part.attacks)} att → ${mean(part.unsaved)}`];
}

/** Who strikes: a lone part by name, else the unit, with a row for each part. */
export function striker(strike: Strike, unit: string): { title: string; rows: [string, string][] } {
	const rows = strike.parts.map(partRow);
	return rows.length === 1 ? { title: rows[0][0], rows: [] } : { title: unit, rows };
}

function unitCard(unit: LaneUnit, measure: Measure) {
	const dims = measure(`${unit.frontage} × ${unit.ranks}`, 'mono');
	const texts = [...unit.options.map((option) => option.name), unit.weapon];
	const chipWidths = texts.map((text) => measure(text, 'chip') + 18);
	const width = Math.max(
		UNIT.least,
		2 * INSET + measure(unit.name, 'title') + 12 + measure(`×${unit.size}`, 'mono'),
		2 * INSET + Math.max(...chipWidths),
		2 * INSET + unit.frontage * 7 + 12 + dims
	);
	const chips: Chip[] = [];
	let x = INSET;
	let y = UNIT.chips;
	texts.forEach((text, index) => {
		if (x > INSET && x + chipWidths[index] > width - INSET) {
			x = INSET;
			y += UNIT.chip + UNIT.gap;
		}
		chips.push({ text, x, y, width: chipWidths[index], height: UNIT.chip });
		x += chipWidths[index] + UNIT.gap;
	});
	const pitch = Math.min(UNIT.pitch, Math.floor((width - 2 * INSET - dims - 12) / unit.frontage));
	const glyph = y + UNIT.chip + UNIT.glyph;
	const height = glyph + Math.ceil(unit.size / unit.frontage) * pitch + UNIT.bottom;
	return { width, height, chips, pitch, glyph };
}

function strikeCard(title: string, lines: string[], rows: [string, string][], measure: Measure) {
	const pad = 2 * STRIKE.inset;
	const width = Math.max(
		STRIKE.least,
		pad + measure(title, 'title'),
		...lines.map((line) => pad + measure(line, 'mono')),
		...rows.map(
			([name, figures]) => pad + measure(name, 'text') + STRIKE.inset + measure(figures, 'mono')
		)
	);
	const height = rows.length ? STRIKE.rule + rows.length * STRIKE.row + 12 : STRIKE.rule;
	return { width, height };
}

function path(points: Point[]): string {
	return points.map(({ x, y }, index) => `${index ? 'L' : 'M'}${x},${y}`).join(' ');
}

/** Out of one card's side and into another's, turning once in the gap before the second. */
function elbow(from: Point, to: Point, turn: number): string {
	return path([from, { x: turn, y: from.y }, { x: turn, y: to.y }, to]);
}

const right = (box: Box, y = box.y + box.height / 2): Point => ({ x: box.x + box.width, y });
const left = (box: Box, y = box.y + box.height / 2): Point => ({ x: box.x, y });
const centred = (x: number, width: number, y: number, height: number): Box => ({
	x: x - width / 2,
	y: y - height / 2,
	width,
	height
});

/**
 * The whole drawing: two lanes left to right, the units feeding the
 * battlefield, the charge and its reaction, each strike with its casualties,
 * the combat result across both lanes and a Break test for each side. A
 * charge that never reaches meets its reaction, and no round is fought.
 */
export function draw(lanes: FightLanes, measure: Measure): Drawing {
	const units = {
		attacker: unitCard(lanes.units.attacker, measure),
		target: unitCard(lanes.units.target, measure)
	};
	const reaches = lanes.charge?.reaches ?? null;
	const fought = reaches !== 0;
	const events = columns(fought ? lanes : { ...lanes, strikes: [] });
	const strikers = lanes.strikes.map((strike) =>
		striker(strike, lanes.units[strike.side as Lane].name)
	);
	const strikeCards = lanes.strikes.map((strike, index) =>
		strikeCard(strikers[index].title, needs(strike.needed), strikers[index].rows, measure)
	);
	const volleyCard =
		lanes.volley && strikeCard(lanes.units.target.name, needs(lanes.volley.needed), [], measure);
	const pillWidth = (lane: Lane, standing: number) =>
		Math.max(PILL.least, measure(pillText(lanes, lane, standing), 'mono') + 24);
	const eventWidth = (lane: Lane, event: Event | null) => {
		if (!event) return 0;
		if (event.kind === 'volley') return volleyCard!.width;
		if (event.kind === 'strike') return strikeCards[event.strike].width;
		return pillWidth(lane, event.standing);
	};
	const { result: scored } = lanes;
	const shares = [scored.attacker_wins, scored.draw, scored.target_wins];
	const resultWidth = Math.max(
		RESULT.least,
		...LANES.map(
			(lane) =>
				3 * STRIKE.inset +
				measure(lanes.units[lane].name, 'text') +
				measure(mean(scored.scores[lane]), 'mono')
		),
		2 * STRIKE.inset + 3 * (18 + Math.max(...shares.map((p) => measure(percent(p), 'mono'))))
	);
	const breakWidth = Math.max(BREAK.width, OUTCOME.inset + OUTCOME.width);

	const tall = (lane: Lane) =>
		Math.max(
			units[lane].height,
			...events.map((column) => {
				const event = column[lane];
				if (event?.kind === 'strike') return strikeCards[event.strike].height;
				if (event?.kind === 'volley') return volleyCard!.height;
				return 0;
			})
		);
	const room = fought ? 3 * OUTCOME.step : 0;
	const bandTop = { attacker: HEAD + (fought ? room + 26 : SHORT.height + 24), target: 0 };
	const bandHeight = {
		attacker: Math.max(160, tall('attacker') + 28),
		target: Math.max(160, tall('target') + 28)
	};
	bandTop.target = bandTop.attacker + bandHeight.attacker + MIDDLE;
	const track = (lane: Lane) => bandTop[lane] + bandHeight[lane] / 2;
	const between = (track('attacker') + track('target')) / 2;
	const gapMiddle = bandTop.attacker + bandHeight.attacker + MIDDLE / 2;

	const nodes: Placed[] = [];
	const edges: Edge[] = [];
	const labels: Label[] = [];
	const heads: Drawing['heads'] = [];
	let x = LEFT;
	let trailing = 0;
	const column = (width: number, head: string, gap = GAP) => {
		const at = x;
		if (head) heads.push({ x: at + width / 2, text: head });
		x += width + gap;
		trailing = gap;
		return at;
	};
	const reached = reaches === null ? 'reaches' : `reaches ${percent(reaches)}`;
	let clear = 0;
	const opening = (each: Column) => {
		const edge = x - trailing + OPENING;
		const centres = LANES.map((lane) => {
			const event = each[lane];
			if (!event) return 0;
			return Math.max(edge, lane === 'attacker' ? clear : 0) + eventWidth(lane, event) / 2;
		});
		x = Math.max(x, ...centres);
		return x;
	};

	const unitWidth = Math.max(units.attacker.width, units.target.width);
	const unitX = column(unitWidth, 'units');
	const stations: Record<Lane, Box[]> = { attacker: [], target: [] };
	for (const lane of LANES) {
		const card = units[lane];
		const box = centred(unitX + unitWidth / 2, unitWidth, track(lane), card.height);
		nodes.push({
			kind: 'unit',
			id: `unit:${lane}`,
			lane,
			box,
			unit: lanes.units[lane],
			chips: card.chips,
			glyph: card.glyph,
			pitch: card.pitch
		});
		stations[lane].push(box);
	}

	let charge: Box | null = null;
	if (lanes.battlefield && lanes.charge && lanes.reaction) {
		const field = centred(
			column(BATTLEFIELD.width, 'battlefield') + BATTLEFIELD.width / 2,
			BATTLEFIELD.width,
			between,
			BATTLEFIELD.height
		);
		nodes.push({ kind: 'battlefield', id: 'battlefield', box: field });
		const chargeX = column(CHARGE.width, 'charge', WIDE) + CHARGE.width / 2;
		charge = centred(chargeX, CHARGE.width, track('attacker'), CHARGE.height);
		const reaction = centred(chargeX, REACTION.width, track('target'), REACTION.height);
		nodes.push(
			{ kind: 'charge', id: 'charge', box: charge },
			{ kind: 'reaction', id: 'reaction', box: reaction }
		);
		const [a, b] = [stations.attacker[0], stations.target[0]];
		edges.push(
			{ d: elbow(right(a), left(field, field.y + 45), field.x - 20) },
			{ d: elbow(right(b), left(field, field.y + field.height - 35), field.x - 20) },
			{ d: elbow(right(field, field.y + 35), left(charge), charge.x - 20) },
			{
				d: elbow(right(field, field.y + field.height - 25), left(reaction), reaction.x - 20)
			},
			{
				d: path([
					{ x: chargeX, y: charge.y + charge.height },
					{ x: chargeX, y: reaction.y }
				])
			}
		);
		stations.attacker = [charge];
		stations.target = [reaction];
		if (fought) clear = charge.x + charge.width + 4 + measure(reached, 'mono') + 8;
	}

	const casualties: { from: Box; to: Box; lane: Lane; loss: number }[] = [];
	events.forEach((each) => {
		const width = Math.max(
			eventWidth('attacker', each.attacker),
			eventWidth('target', each.target)
		);
		if (each.head && each.attacker)
			x = Math.max(x, clear - (width - eventWidth('attacker', each.attacker)) / 2);
		const centre = each.head ? column(width, each.head) + width / 2 : opening(each);
		const placed: Partial<Record<Lane, Box>> = {};
		for (const lane of LANES) {
			const event = each[lane];
			if (!event) continue;
			const y = track(lane);
			if (event.kind === 'pill') {
				const box = centred(centre, pillWidth(lane, event.standing), y, PILL.height);
				nodes.push({
					kind: 'pill',
					id: `pill:${lane}:${event.standing}`,
					lane,
					box,
					text: pillText(lanes, lane, event.standing)
				});
				placed[lane] = box;
			} else if (event.kind === 'volley') {
				const box = centred(centre, volleyCard!.width, y, volleyCard!.height);
				nodes.push({ kind: 'volley', id: 'volley', lane, box });
				placed[lane] = box;
			} else {
				const card = strikeCards[event.strike];
				const box = centred(centre, card.width, y, card.height);
				nodes.push({
					kind: 'strike',
					id: `strike:${event.strike}`,
					lane,
					box,
					strike: lanes.strikes[event.strike],
					...strikers[event.strike]
				});
				placed[lane] = box;
			}
			stations[lane].push(placed[lane]!);
		}
		for (const lane of LANES) {
			const event = each[lane];
			const struck = placed[other(lane)];
			if (event?.kind !== 'pill' || event.standing === 0 || !struck) continue;
			const standing = lanes.standing[lane];
			const loss = standing[event.standing - 1].models - standing[event.standing].models;
			casualties.push({ from: struck, to: placed[lane]!, lane: other(lane), loss });
		}
	});

	for (const { from, to, lane, loss } of casualties) {
		const down = lane === 'attacker';
		const at = from.x + from.width / 2;
		edges.push({
			d: path([
				{ x: at, y: down ? from.y + from.height : from.y },
				{ x: at, y: down ? to.y : to.y + to.height }
			]),
			tone: lane
		});
		labels.push({
			x: at + 8,
			y: gapMiddle + 4,
			text: `−${mean(loss)}`,
			tone: lane,
			anchor: 'start'
		});
	}

	for (const lane of LANES) {
		const run = stations[lane];
		run.slice(1).forEach((box, index) =>
			edges.push({
				d: path([right(run[index], track(lane)), left(box, track(lane))])
			})
		);
	}

	if (fought) {
		const result = centred(
			column(resultWidth, 'combat result', WIDE) + resultWidth / 2,
			resultWidth,
			between,
			RESULT.height
		);
		nodes.push({ kind: 'result', id: 'result', box: result });
		const breakX = column(breakWidth, 'break tests');
		const entry = {
			attacker: result.y + result.height * 0.3,
			target: result.y + result.height * 0.7
		};
		for (const lane of LANES) {
			const run = stations[lane];
			edges.push({
				d: elbow(right(run.at(-1)!, track(lane)), left(result, entry[lane]), result.x - 20)
			});
			const test = {
				x: breakX,
				y: track(lane) - BREAK.height / 2,
				width: BREAK.width,
				height: BREAK.height
			};
			nodes.push({ kind: 'break', id: `break:${lane}`, lane, box: test });
			edges.push({ d: elbow(right(result, entry[lane]), left(test), test.x - 34) });
			labels.push({
				x: test.x - 17,
				y: track(lane) - 6,
				text: percent(lanes.breaks[lane].taken),
				anchor: 'middle'
			});
			const spine = test.x + 16;
			const outcomes = [
				['Give Ground', lanes.breaks[lane].give_ground],
				['Fall Back in Good Order', lanes.breaks[lane].fall_back_in_good_order],
				['Break', lanes.breaks[lane].break]
			] as const;
			const tops = outcomes.map((_, index) =>
				lane === 'attacker'
					? bandTop.attacker - 12 - (3 - index) * OUTCOME.step
					: bandTop.target + bandHeight.target + 12 + index * OUTCOME.step
			);
			const reach =
				lane === 'attacker' ? tops[0] + OUTCOME.height / 2 : tops[2] + OUTCOME.height / 2;
			edges.push({
				d: path([
					{ x: spine, y: lane === 'attacker' ? test.y : test.y + test.height },
					{ x: spine, y: reach }
				]),
				bare: true
			});
			outcomes.forEach(([name, p], index) => {
				const box = {
					x: test.x + OUTCOME.inset,
					y: tops[index],
					width: OUTCOME.width,
					height: OUTCOME.height
				};
				nodes.push({ kind: 'outcome', id: `break:${lane}`, lane, box, name, p });
				edges.push({ d: path([{ x: spine, y: box.y + box.height / 2 }, left(box)]) });
			});
		}
	}

	if (charge && fought) {
		labels.push({
			x: charge.x + charge.width + 4,
			y: track('attacker') - 7,
			text: reached,
			anchor: 'start'
		});
	}
	if (charge && reaches !== 1) {
		const next = stations.attacker[1];
		const short = {
			x: next?.x ?? charge.x + charge.width + WIDE,
			y: bandTop.attacker - SHORT.height - 12,
			width: SHORT.width,
			height: SHORT.height
		};
		nodes.push({ kind: 'short', id: 'charge', box: short });
		const from = right(charge, charge.y + 16);
		const to = left(short);
		edges.push({
			d: `M${from.x},${from.y} C${from.x + 26},${from.y} ${to.x - 22},${to.y} ${to.x},${to.y}`
		});
		labels.push({
			x: charge.x + charge.width - 2,
			y: charge.y - 6,
			text: reaches === null ? 'falls short' : `falls short ${percent(1 - reaches)}`,
			anchor: 'end'
		});
	}

	const width = Math.max(...nodes.map(({ box }) => box.x + box.width)) + LEFT;
	const height = bandTop.target + bandHeight.target + 24 + room;
	const band = (lane: Lane): Box => ({
		x: LEFT - 10,
		y: bandTop[lane],
		width: width - 2 * (LEFT - 10),
		height: bandHeight[lane]
	});
	return {
		width,
		height,
		bands: { attacker: band('attacker'), target: band('target') },
		heads: merged(heads),
		nodes,
		edges,
		labels
	};
}

/** A lane's models standing: the count it fielded at the start, the mean after. */
export function pillText(
	lanes: Pick<FightLanes, 'standing'>,
	lane: Lane,
	standing: number
): string {
	const models = lanes.standing[lane][standing].models;
	return standing === 0 ? String(models) : mean(models);
}

/** One head over each run of columns printed alike: both sides striking at one Initiative. */
function merged(heads: Drawing['heads']): Drawing['heads'] {
	const runs: { xs: number[]; text: string }[] = [];
	for (const head of heads) {
		const run = runs.at(-1);
		if (run?.text === head.text) run.xs.push(head.x);
		else runs.push({ xs: [head.x], text: head.text });
	}
	return runs.map(({ xs, text }) => ({ x: (xs[0] + xs.at(-1)!) / 2, text }));
}
