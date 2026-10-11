import { describe, expect, it } from 'vitest';

import type { FightLanes, Strike } from '$lib/api/client';
import princes from './fixtures/princes-charge-archers.json';
import {
	chargeFace,
	formation,
	resultFace,
	spread,
	strikeFace,
	type Box,
	type Face,
	type Measure
} from './faces';
import { columns, draw, type Drawing } from './layout';

const strike = (slot: string, side: 'attacker' | 'target') =>
	({ slot, label: slot, side }) as Strike;
const standing = (...after: (string | null)[]) =>
	after.map((each) => ({ after: each, models: { mean: 0, sd: 0, least: 0, distribution: [] } }));

describe('the columns of a fight', () => {
	it('drops each strike as a pill into the other lane, the lane hit first opening on its models', () => {
		const lanes = {
			volley: null,
			strikes: [
				strike('initiative-9', 'attacker'),
				strike('initiative-7', 'attacker'),
				strike('initiative-2', 'target')
			],
			standing: {
				attacker: standing(null, 'initiative-2'),
				target: standing(null, 'initiative-9', 'initiative-7')
			}
		} satisfies Pick<FightLanes, 'volley' | 'strikes' | 'standing'>;

		expect(columns(lanes)).toEqual([
			{ head: '', attacker: null, target: { kind: 'pill', standing: 0 } },
			{
				head: 'initiative-9',
				attacker: { kind: 'strike', strike: 0 },
				target: { kind: 'pill', standing: 1 }
			},
			{
				head: 'initiative-7',
				attacker: { kind: 'strike', strike: 1 },
				target: { kind: 'pill', standing: 2 }
			},
			{
				head: 'initiative-2',
				attacker: { kind: 'pill', standing: 1 },
				target: { kind: 'strike', strike: 2 }
			}
		]);
	});

	it('opens the charger on its models when a Stand & Shoot hits it before anyone strikes', () => {
		const lanes = {
			volley: {} as FightLanes['volley'],
			strikes: [strike('initiative-5', 'attacker')],
			standing: {
				attacker: standing(null, 'volley'),
				target: standing(null, 'initiative-5')
			}
		} satisfies Pick<FightLanes, 'volley' | 'strikes' | 'standing'>;

		expect(columns(lanes).map((column) => [column.attacker, column.target])).toEqual([
			[{ kind: 'pill', standing: 0 }, null],
			[{ kind: 'pill', standing: 1 }, { kind: 'volley' }],
			[
				{ kind: 'strike', strike: 0 },
				{ kind: 'pill', standing: 1 }
			]
		]);
	});
});

describe('a formation', () => {
	const ranks = (size: number, frontage: number, command: Parameters<typeof formation>[2]) => {
		const models = formation(size, frontage, command);
		return Array.from({ length: Math.ceil(size / frontage) }, (_, rank) =>
			models.filter((model) => model.rank === rank).map((model) => model.command)
		);
	};

	it('stands the command group in the middle of the front rank', () => {
		expect(ranks(5, 4, ['champion'])[0]).toEqual([null, 'champion', null, null]);
		expect(ranks(10, 5, ['champion'])[0]).toEqual([null, null, 'champion', null, null]);
		expect(ranks(10, 5, ['champion', 'standard', 'musician'])[0]).toEqual([
			null,
			'champion',
			'standard',
			'musician',
			null
		]);
	});

	it('stands the champion in front when the command group is wider than the front', () => {
		expect(ranks(5, 2, ['champion', 'standard', 'musician'])).toEqual([
			['champion', 'standard'],
			['musician', null],
			[null]
		]);
	});

	it('stands each model on its base, both units at one scale', () => {
		const drawing = draw(princes as FightLanes, (text) => text.length * 7);
		const scales = drawing.nodes.flatMap((node) => {
			if (node.kind !== 'unit') return [];
			const { width_mm, depth_mm } = princes.units[node.lane].base;
			return node.face.marks.flatMap((mark) =>
				mark.kind === 'model' ? [`${mark.box.width / width_mm} ${mark.box.height / depth_mm}`] : []
			);
		});

		expect(scales).toHaveLength(15);
		expect(new Set(scales).size).toBe(1);
		expect(scales[0].split(' ')[0]).toBe(scales[0].split(' ')[1]);
	});
});

describe('the chips on a unit card', () => {
	const measure: Measure = (text) => text.length * 7;
	const chips = (options: string[], held: string[]) => {
		const target = {
			...princes.units.target,
			options: options.map((name) => ({ id: name, name })),
			held
		};
		const lanes = {
			...princes,
			charge: { ...princes.charge, reaches: 1 },
			units: { ...princes.units, target }
		} as FightLanes;
		const card = draw(lanes, measure).nodes.find(
			(node) => node.kind === 'unit' && node.lane === 'target'
		);
		if (card?.kind !== 'unit') throw new Error('the target has no card');
		return card.face.marks.flatMap((mark) =>
			mark.kind === 'chip' ? [[mark.text, mark.held]] : []
		);
	};

	it('greys every option and highlights each piece held, one an option among them', () => {
		expect(chips(['Great Weapon', 'Shield', 'Veteran'], ['Great Weapon'])).toEqual([
			['Great Weapon', false],
			['Shield', false],
			['Veteran', false],
			['Great Weapon', true]
		]);
	});
});

describe('a charge drawn by the chance it reaches', () => {
	const measure: Measure = (text) => text.length * 7;
	const drawn = (reaches: number) =>
		draw({ ...princes, charge: { ...princes.charge, reaches } } as FightLanes, measure);
	const kinds = (drawing: Drawing) => drawing.nodes.map((node) => node.kind).sort();
	const texts = (drawing: Drawing) => drawing.labels.map((label) => label.text);

	it('leaves out the Falls short branch of a charge sure to reach', () => {
		const sure = drawn(1);
		const likely = drawn(0.75);

		expect(kinds(sure)).toEqual(kinds(likely).filter((kind) => kind !== 'short'));
		expect(sure.edges).toHaveLength(likely.edges.length - 1);
		expect(texts(sure).filter((text) => text.startsWith('falls short'))).toEqual([]);
	});

	it('ends a charge that never reaches on its Stand & Shoot', () => {
		const never = drawn(0);

		expect(kinds(never)).toEqual(
			[
				'unit',
				'unit',
				'battlefield',
				'charge',
				'reaction',
				'short',
				'volley',
				'pill',
				'pill'
			].sort()
		);
		expect(never.heads.map((head) => head.text)).toEqual([
			'units',
			'battlefield',
			'charge',
			'Stand & Shoot'
		]);
		expect(texts(never)).toEqual(['falls short 100%']);
	});
});

describe('a fight drawn with one node open, five rules on its result and Break tests', () => {
	const measure: Measure = (text) => text.length * 7;
	const rules = princes.volley.rules;
	const lanes = {
		...princes,
		charge: { ...princes.charge, reaches: 0.75 },
		result: { ...princes.result, rules },
		breaks: {
			attacker: { ...princes.breaks.attacker, rules },
			target: { ...princes.breaks.target, rules }
		}
	} as FightLanes;
	const ids = [...new Set(draw(lanes, measure).nodes.map((node) => node.id))];
	const overlap = (one: Box, two: Box) =>
		one.x < two.x + two.width &&
		two.x < one.x + one.width &&
		one.y < two.y + two.height &&
		two.y < one.y + one.height;

	it.each(ids)('makes room for %s in its lane, clear of every other card and label', (id) => {
		const drawing = draw(lanes, measure, id);
		const boxes = drawing.nodes.map((node) => node.box);
		const labels = drawing.labels.map((label): Box => {
			const width = measure(label.text, 'mono');
			const shift = { start: 0, middle: width / 2, end: width }[label.anchor];
			return { x: label.x - shift, y: label.y - 9, width, height: 12 };
		});
		const clashes = boxes.flatMap((one, index) =>
			[...boxes.slice(index + 1), ...labels]
				.filter((two) => overlap(one, two))
				.map((two) => [one, two])
		);

		const { attacker, target } = drawing.bands;
		const both = { ...attacker, height: target.y + target.height - attacker.y };
		const strays = drawing.nodes.filter((node) => {
			if (node.kind === 'outcome' || node.kind === 'short') return false;
			const lane = node.kind === 'reaction' ? 'target' : 'lane' in node ? node.lane : null;
			const band = lane ? drawing.bands[lane] : both;
			return node.box.y < band.y || node.box.y + node.box.height > band.y + band.height;
		});

		expect(clashes).toEqual([]);
		expect(strays.map((node) => node.id)).toEqual([]);
		expect(Math.min(...boxes.map((box) => box.y))).toBeGreaterThan(46);
		expect(Math.max(...boxes.map((box) => box.y + box.height))).toBeLessThan(drawing.height);
	});

	it('makes room inside a unit edited in place for its editor, clear of every other card', () => {
		const drawing = draw(lanes, measure, 'unit:target', { lane: 'target', height: 300 });
		const edited = drawing.nodes.find((node) => node.id === 'unit:target');
		if (edited?.kind !== 'unit' || !edited.face.slot) throw new Error('the target has no room');
		const { slot } = edited.face;

		expect(slot.height).toBe(300);
		expect(slot.y + slot.height).toBeLessThan(edited.box.height);
		expect(
			drawing.nodes.filter((node) => node !== edited && overlap(node.box, edited.box))
		).toEqual([]);
	});
});

describe('a count on a card', () => {
	it('reads as its mean ± its standard deviation, and plain when it cannot vary', () => {
		expect(spread({ mean: 4.44, sd: 1.62 })).toBe('4.4 ± 1.6');
		expect(spread({ mean: 0.228, sd: 0.472 })).toBe('0.23 ± 0.47');
		expect(spread({ mean: 10, sd: 0 })).toBe('10');
	});
});

describe('a strike opened', () => {
	const measure: Measure = (text) => text.length * 7;
	const strike = princes.strikes[0] as Strike;
	const shown = (face: Face) =>
		face.marks.flatMap((mark) =>
			mark.kind === 'chart' ? [mark.name] : mark.kind === 'rule' ? [mark.rule.name] : []
		);
	const rules = ['Armour Bane (1)', 'Ithilmar Weapons', 'Parry'];

	it('charts its unsaved wounds, its attacks where they vary, and lists the rules on it', () => {
		const fixed = { ...strike, attacks: { ...strike.attacks, sd: 0 } };

		expect(shown(strikeFace(strike, 'Dragon Princes', measure, false))).toEqual([]);
		expect(shown(strikeFace(strike, 'Dragon Princes', measure, true))).toEqual([
			'unsaved',
			'attacks',
			...rules
		]);
		expect(shown(strikeFace(fixed, 'Dragon Princes', measure, true))).toEqual([
			'unsaved',
			...rules
		]);
	});
});

describe('who strikes', () => {
	const measure: Measure = (text) => text.length * 7;
	const texts = (face: Face) =>
		face.marks.flatMap((mark) => (mark.kind === 'text' ? [mark.text] : []));

	it('counts the models of each part by their spread, a champion the volley may fell too', () => {
		const [princely, , archers] = princes.strikes as Strike[];

		expect(texts(strikeFace(archers, 'Elven Archers', measure, false))[0]).toBe(
			'Elven Archer ×4.0 ± 1.7'
		);
		expect(texts(strikeFace(princely, 'Dragon Princes', measure, true))).toEqual(
			expect.arrayContaining(['Drakemaster ×1.00 ± 0.00', 'Dragon Prince ×3.0 ± 0.15'])
		);
	});
});

describe('a charge opened', () => {
	it('works out its maximum possible charge range term by term, ruling its chart at the distance', () => {
		const charge = princes.charge as NonNullable<FightLanes['charge']>;
		const face = chargeFace(charge, (text) => text.length * 7, true);
		const texts = face.marks.flatMap((mark) => (mark.kind === 'text' ? [mark.text] : []));
		const rules = face.marks.flatMap((mark) => (mark.kind === 'chart' ? [mark.rule] : []));

		expect(texts).toEqual(
			expect.arrayContaining(['98%', 'Movement 8 + 6 + Swiftstride 3 = 17in', '17in'])
		);
		expect(rules).toEqual([12]);
	});
});

describe('a combat result opened', () => {
	it("breaks each side's score into its parts, and charts the margin by who wins", () => {
		const face = resultFace(princes as FightLanes, (text) => text.length * 7, true);
		const texts = face.marks.flatMap((mark) => (mark.kind === 'text' ? [mark.text] : []));
		const charts = face.marks.flatMap((mark) => (mark.kind === 'chart' ? [mark] : []));
		const shares = face.marks.flatMap((mark) => (mark.kind === 'shares' ? mark.shares : []));
		const margin = charts.find((chart) => chart.name === 'margin')!;
		const total = (chances: number[]) => chances.reduce((sum, p) => sum + p, 0);
		const [massed] = princes.result.scores.target.rules;

		expect(charts.map((chart) => chart.name)).toEqual(['Wounds', 'Wounds', 'margin']);
		expect(margin.layers.map(([tone, chances]) => [tone, total(chances)])).toEqual(
			shares.map(([way, p]) => [way, expect.closeTo(p, 10)])
		);
		expect(texts).toEqual(
			expect.arrayContaining(['Rank Bonus', 'Flank or Rear', massed.name, spread(massed.points)])
		);
	});
});
