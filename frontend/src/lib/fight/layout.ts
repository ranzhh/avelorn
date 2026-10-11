import type { FightLanes, LaneUnit, Needed, Strike } from '$lib/api/client';

/** A lane of the drawing: the charger's above, its target's below. */
export type Lane = 'attacker' | 'target';
export const LANES: Lane[] = ['attacker', 'target'];
export const other = (lane: Lane): Lane => (lane === 'attacker' ? 'target' : 'attacker');

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

/** A lane's models standing: the count it fielded at the start, the mean after. */
export function pillText(
	lanes: Pick<FightLanes, 'standing'>,
	lane: Lane,
	standing: number
): string {
	const models = lanes.standing[lane][standing].models;
	return standing === 0 ? String(models) : mean(models);
}
