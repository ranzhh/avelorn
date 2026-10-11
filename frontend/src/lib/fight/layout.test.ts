import { describe, expect, it } from 'vitest';

import type { FightLanes, Strike } from '$lib/api/client';
import princes from './fixtures/princes-charge-archers.json';
import { formation, type Box, type Measure } from './faces';
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

	it('keeps room for a letter in each square of a ten-wide formation', () => {
		const target = { ...princes.units.target, size: 30, frontage: 10, ranks: 3 };
		const lanes = {
			...princes,
			charge: { ...princes.charge, reaches: 1 },
			units: { ...princes.units, target }
		} as FightLanes;
		const card = draw(lanes, (text) => text.length * 7).nodes.find(
			(node) => node.kind === 'unit' && node.lane === 'target'
		);
		if (card?.kind !== 'unit') throw new Error('the target has no card');
		const squares = card.face.marks.flatMap((mark) => (mark.kind === 'model' ? [mark.box] : []));

		expect(new Set(squares.map((square) => square.width))).toEqual(new Set([12]));
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
		expect(texts(sure)).toContain('reaches 100%');
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
		expect(texts(never).sort()).toEqual(['falls short 100%', '−0.23']);
	});
});

describe('a fight drawn with one node open', () => {
	const measure: Measure = (text) => text.length * 7;
	const lanes = { ...princes, charge: { ...princes.charge, reaches: 0.75 } } as FightLanes;
	const ids = [...new Set(draw(lanes, measure).nodes.map((node) => node.id))];
	const overlap = (one: Box, two: Box) =>
		one.x < two.x + two.width &&
		two.x < one.x + one.width &&
		one.y < two.y + two.height &&
		two.y < one.y + one.height;

	it.each(ids)('makes room for %s, every card and label clear of the others', (id) => {
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

		expect(clashes).toEqual([]);
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
