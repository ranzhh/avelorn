import type { FightLanes } from '$lib/api/client';
import { percent } from '$lib/charts/scale';
import {
	LANES,
	breakFace,
	chargeFace,
	pillFace,
	resultFace,
	strikeFace,
	unitFace,
	volleyFace,
	type Box,
	type Face,
	type Lane,
	type Measure,
	type Point
} from './faces';

export { LANES, type Lane };
export const other = (lane: Lane): Lane => (lane === 'attacker' ? 'target' : 'attacker');

const BATTLEFIELD = { width: 160, height: 140 };
const REACTION = { width: 170, height: 80 };
const SHORT = { width: 120, height: 36 };
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

/** A node of the drawing; a card drawn from its face wears its lane's colour, the result neither. */
export type Placed =
	| {
			kind: 'unit' | 'charge' | 'volley' | 'strike' | 'pill' | 'break';
			id: string;
			lane: Lane;
			box: Box;
			face: Face;
	  }
	| { kind: 'result'; id: string; lane: null; box: Box; face: Face }
	| { kind: 'battlefield'; id: string; box: Box }
	| { kind: 'reaction'; id: string; box: Box }
	| { kind: 'short'; id: string; box: Box }
	| { kind: 'outcome'; id: string; lane: Lane; box: Box; name: string; p: number };

export interface Edge {
	d: string;
	tone?: Lane;
	/** Drawn without an arrowhead: a spine the arrows branch off. */
	bare?: boolean;
}

export interface Label extends Point {
	text: string;
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

/** A unit edited in place, and how tall its editor stands. */
export interface Editor {
	lane: Lane;
	height: number;
}

/**
 * The whole drawing: two lanes left to right, the units feeding the
 * battlefield, the charge and its reaction, each strike with its casualties,
 * the combat result across both lanes and a Break test for each side. A
 * charge that never reaches meets its reaction, and no round is fought.
 *
 * The node `open` shows its whole face, a unit edited in place makes room
 * for its `editor`, and the lanes widen and deepen to hold them.
 */
export function draw(
	lanes: FightLanes,
	measure: Measure,
	open: string | null = null,
	editor: Editor | null = null
): Drawing {
	const reaches = lanes.charge?.reaches ?? null;
	const fought = reaches !== 0;
	const events = columns(fought ? lanes : { ...lanes, strikes: [] });
	const editing = (lane: Lane) => (editor?.lane === lane ? editor.height : null);
	const unitFaces = (least: number) => ({
		attacker: unitFace(
			lanes.units.attacker,
			measure,
			open === 'unit:attacker',
			least,
			editing('attacker')
		),
		target: unitFace(lanes.units.target, measure, open === 'unit:target', least, editing('target'))
	});
	const natural = unitFaces(0);
	const unitWidth = Math.max(natural.attacker.width, natural.target.width);
	const units = unitFaces(unitWidth);
	const chargeCard = lanes.charge && chargeFace(lanes.charge, measure, open === 'charge');
	const volleyCard =
		lanes.volley && volleyFace(lanes.volley, lanes.units.target.name, measure, open === 'volley');
	const strikeCards = lanes.strikes.map((strike, index) =>
		strikeFace(strike, lanes.units[strike.side as Lane].name, measure, open === `strike:${index}`)
	);
	const eventFace = (lane: Lane, event: Event): Face => {
		if (event.kind === 'volley') return volleyCard!;
		if (event.kind === 'strike') return strikeCards[event.strike];
		const id = `pill:${lane}:${event.standing}`;
		return pillFace(lanes.standing[lane][event.standing].models, lane, measure, open === id);
	};
	const eventWidth = (lane: Lane, event: Event | null) =>
		event ? eventFace(lane, event).width : 0;
	const resultCard = resultFace(lanes, measure, open === 'result');
	const breakCards = {
		attacker: breakFace(lanes.breaks.attacker, measure, open === 'break:attacker'),
		target: breakFace(lanes.breaks.target, measure, open === 'break:target')
	};
	const breakWidth = Math.max(
		OUTCOME.inset + OUTCOME.width,
		...LANES.map((lane) => breakCards[lane].width)
	);
	const charged = lanes.battlefield && chargeCard && lanes.reaction;

	const tall = (lane: Lane) =>
		Math.max(
			units[lane].height,
			charged ? (lane === 'attacker' ? chargeCard.height : REACTION.height) : 0,
			fought ? breakCards[lane].height : 0,
			...events.map((column) => {
				const event = column[lane];
				return event ? eventFace(lane, event).height : 0;
			})
		);
	const across = Math.max(charged ? BATTLEFIELD.height : 0, fought ? resultCard.height : 0);
	const room = fought ? 3 * OUTCOME.step : 0;
	const bandTop = { attacker: HEAD + (fought ? room + 26 : SHORT.height + 24), target: 0 };
	const bandHeight = {
		attacker: Math.max(160, tall('attacker') + 28),
		target: Math.max(160, tall('target') + 28)
	};
	const { attacker: upper, target: lower } = bandHeight;
	const above = (3 * upper + lower) / 4 + MIDDLE / 2;
	const below = (upper + 3 * lower) / 4 + MIDDLE / 2;
	const deeper = Math.max(0, across / 2 + 14 - Math.min(above, below));
	bandHeight.attacker += deeper;
	bandHeight.target += deeper;
	bandTop.target = bandTop.attacker + bandHeight.attacker + MIDDLE;
	const track = (lane: Lane) => bandTop[lane] + bandHeight[lane] / 2;
	const between = (track('attacker') + track('target')) / 2;

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
	const clear = { attacker: 0, target: 0 };
	const opening = (each: Column) => {
		const edge = x - trailing + OPENING;
		const centres = LANES.map((lane) => {
			const event = each[lane];
			return event ? Math.max(edge, clear[lane]) + eventWidth(lane, event) / 2 : 0;
		});
		x = Math.max(x, ...centres);
		for (const lane of LANES)
			if (each[lane]) clear[lane] = x + eventWidth(lane, each[lane]) / 2 + OPENING;
		return x;
	};

	const unitX = column(unitWidth, 'units');
	const stations: Record<Lane, Box[]> = { attacker: [], target: [] };
	for (const lane of LANES) {
		const face = units[lane];
		const box = centred(unitX + unitWidth / 2, unitWidth, track(lane), face.height);
		nodes.push({ kind: 'unit', id: `unit:${lane}`, lane, box, face });
		stations[lane].push(box);
	}

	let charge: Box | null = null;
	if (charged) {
		const field = centred(
			column(BATTLEFIELD.width, 'battlefield') + BATTLEFIELD.width / 2,
			BATTLEFIELD.width,
			between,
			BATTLEFIELD.height
		);
		nodes.push({ kind: 'battlefield', id: 'battlefield', box: field });
		const face = chargeCard;
		const chargeX = column(face.width, 'charge', WIDE) + face.width / 2;
		charge = centred(chargeX, face.width, track('attacker'), face.height);
		const reaction = centred(chargeX, REACTION.width, track('target'), REACTION.height);
		nodes.push(
			{ kind: 'charge', id: 'charge', lane: 'attacker', box: charge, face },
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
		if (fought) clear.attacker = charge.x + charge.width + 4 + measure(reached, 'mono') + 8;
	}

	const casualties: { from: Box; to: Box; lane: Lane }[] = [];
	events.forEach((each) => {
		const width = Math.max(
			eventWidth('attacker', each.attacker),
			eventWidth('target', each.target)
		);
		for (const lane of LANES)
			if (each.head && each[lane])
				x = Math.max(x, clear[lane] - (width - eventWidth(lane, each[lane])) / 2);
		const centre = each.head ? column(width, each.head) + width / 2 : opening(each);
		const placed: Partial<Record<Lane, Box>> = {};
		for (const lane of LANES) {
			const event = each[lane];
			if (!event) continue;
			const face = eventFace(lane, event);
			const box = centred(centre, face.width, track(lane), face.height);
			const id =
				event.kind === 'pill'
					? `pill:${lane}:${event.standing}`
					: event.kind === 'strike'
						? `strike:${event.strike}`
						: 'volley';
			nodes.push({ kind: event.kind, id, lane, box, face });
			placed[lane] = box;
			stations[lane].push(box);
		}
		for (const lane of LANES) {
			const event = each[lane];
			const struck = placed[other(lane)];
			if (event?.kind !== 'pill' || event.standing === 0 || !struck) continue;
			casualties.push({ from: struck, to: placed[lane]!, lane: other(lane) });
		}
	});

	for (const { from, to, lane } of casualties) {
		const down = lane === 'attacker';
		const at = from.x + from.width / 2;
		edges.push({
			d: path([
				{ x: at, y: down ? from.y + from.height : from.y },
				{ x: at, y: down ? to.y : to.y + to.height }
			]),
			tone: lane
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
			column(resultCard.width, 'combat result', WIDE) + resultCard.width / 2,
			resultCard.width,
			between,
			resultCard.height
		);
		nodes.push({ kind: 'result', id: 'result', lane: null, box: result, face: resultCard });
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
			const face = breakCards[lane];
			const test = {
				x: breakX,
				y: track(lane) - face.height / 2,
				width: face.width,
				height: face.height
			};
			nodes.push({ kind: 'break', id: `break:${lane}`, lane, box: test, face });
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
