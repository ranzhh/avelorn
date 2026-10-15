import type { VolleyLanes } from '$lib/api/client';
import { percent, percents } from '$lib/charts/scale';
import {
	LANES,
	NONE,
	left as standing,
	pillFace,
	testFace,
	unitFace,
	volleyFace,
	type Box,
	type Lane,
	type Measure
} from './faces';
import {
	GAP,
	HEAD,
	LEFT,
	MIDDLE,
	OUTCOME,
	WIDE,
	centred,
	elbow,
	left,
	path,
	right,
	type Drawing,
	type Edge,
	type Editor,
	type Label,
	type Placed
} from './layout';
import { battlefieldSize } from './field';
import { panicked, type View } from './odds';

const OPENING = 24;

/**
 * A volley drawn as the fight is: the shooter's lane above its target's, the
 * units feeding the battlefield, the shots in the shooter's lane falling as
 * casualties into the target's, and the target's Panic test with its outcomes
 * read in `view`. The node `open` shows its whole face, a unit edited in place
 * makes room for its `editor`, and a `mapped` battlefield reads its distance
 * off the table's blocks.
 */
export function drawVolley(
	lanes: VolleyLanes,
	measure: Measure,
	open: string | null = null,
	editor: Editor | null = null,
	mapped = false,
	view: View = 'conditional'
): Drawing {
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
	const field = battlefieldSize(
		[mapped ? 'read' : 'inches', 'read', 'toggle'],
		mapped && open === 'battlefield'
	);
	const shots = volleyFace(lanes.volley, lanes.units.attacker.name, measure, open === 'volley');
	const size = lanes.units.target.size;
	const before = pillFace(NONE(size), 'target', measure, open === 'pill:target:0');
	const after = pillFace(
		standing(size, lanes.volley.casualties),
		'target',
		measure,
		open === 'pill:target:1'
	);
	const test = testFace('Panic test', lanes.panic, measure, open === 'panic');
	const outcomes = panicked(lanes.panic, view);

	const room = 3 * OUTCOME.step;
	const bandHeight = {
		attacker: Math.max(160, Math.max(units.attacker.height, shots.height) + 28),
		target: Math.max(
			160,
			Math.max(units.target.height, before.height, after.height, test.height) + 28
		)
	};
	const { attacker: upper, target: lower } = bandHeight;
	const above = (3 * upper + lower) / 4 + MIDDLE / 2;
	const below = (upper + 3 * lower) / 4 + MIDDLE / 2;
	const deeper = Math.max(0, field.height / 2 + 14 - Math.min(above, below));
	bandHeight.attacker += deeper;
	bandHeight.target += deeper;
	const bandTop = { attacker: HEAD + 14, target: 0 };
	bandTop.target = bandTop.attacker + bandHeight.attacker + MIDDLE;
	const track = (lane: Lane) => bandTop[lane] + bandHeight[lane] / 2;
	const between = (track('attacker') + track('target')) / 2;

	const nodes: Placed[] = [];
	const edges: Edge[] = [];
	const labels: Label[] = [];
	const heads: Drawing['heads'] = [];
	let x = LEFT;
	const column = (width: number, head: string, gap = GAP) => {
		const at = x;
		if (head) heads.push({ x: at + width / 2, text: head });
		x += width + gap;
		return at;
	};

	const unitX = column(unitWidth, 'units');
	const unitBoxes = {} as Record<Lane, Box>;
	for (const lane of LANES) {
		const face = units[lane];
		const box = centred(unitX + unitWidth / 2, unitWidth, track(lane), face.height);
		nodes.push({ kind: 'unit', id: `unit:${lane}`, lane, box, face });
		unitBoxes[lane] = box;
	}

	const ground = centred(
		column(field.width, 'battlefield') + field.width / 2,
		field.width,
		between,
		field.height
	);
	nodes.push({ kind: 'battlefield', id: 'battlefield', box: ground });

	const start = centred(
		column(before.width, '', OPENING) + before.width / 2,
		before.width,
		track('target'),
		before.height
	);
	nodes.push({ kind: 'pill', id: 'pill:target:0', lane: 'target', box: start, face: before });

	const shotWidth = Math.max(shots.width, after.width);
	const shotX = column(shotWidth, 'shoot', WIDE) + shotWidth / 2;
	const volley = centred(shotX, shots.width, track('attacker'), shots.height);
	const thinned = centred(shotX, after.width, track('target'), after.height);
	nodes.push(
		{ kind: 'volley', id: 'volley', lane: 'attacker', box: volley, face: shots },
		{ kind: 'pill', id: 'pill:target:1', lane: 'target', box: thinned, face: after }
	);

	const testWidth = Math.max(OUTCOME.inset + OUTCOME.width, test.width);
	const testX = column(testWidth, 'panic test');
	const panic = {
		x: testX,
		y: track('target') - test.height / 2,
		width: test.width,
		height: test.height
	};
	nodes.push({ kind: 'break', id: 'panic', lane: 'target', box: panic, face: test });

	const [over, under] = [0.3, 0.7].map((share) => ground.y + ground.height * share);
	edges.push(
		{ d: elbow(right(unitBoxes.attacker), left(ground, over), ground.x - 20) },
		{ d: elbow(right(unitBoxes.target), left(ground, under), ground.x - 20) },
		{ d: elbow(right(ground, over), left(volley), volley.x - 20) },
		{ d: elbow(right(ground, under), left(start), start.x - 12) },
		{ d: path([right(start), left(thinned)]) },
		{
			d: path([
				{ x: shotX, y: volley.y + volley.height },
				{ x: shotX, y: thinned.y }
			]),
			tone: 'attacker'
		},
		{ d: path([right(thinned), left(panic)]) }
	);
	labels.push({
		x: panic.x - 17,
		y: track('target') - 6,
		text: percent(lanes.panic.taken),
		anchor: 'middle'
	});

	const spine = panic.x + 16;
	const tops = outcomes.map(
		(_, index) => bandTop.target + bandHeight.target + 12 + index * OUTCOME.step
	);
	edges.push({
		d: path([
			{ x: spine, y: panic.y + panic.height },
			{ x: spine, y: tops[2] + OUTCOME.height / 2 }
		]),
		bare: true
	});
	const texts = percents(outcomes.map(([, p]) => p));
	outcomes.forEach(([name, p], index) => {
		const box = {
			x: panic.x + OUTCOME.inset,
			y: tops[index],
			width: OUTCOME.width,
			height: OUTCOME.height
		};
		const worst = name === 'Flee';
		const text = texts[index];
		nodes.push({ kind: 'outcome', id: 'panic', lane: 'target', box, name, p, text, worst });
		edges.push({ d: path([{ x: spine, y: box.y + box.height / 2 }, left(box)]) });
	});

	const width = Math.max(...nodes.map(({ box }) => box.x + box.width)) + LEFT;
	const band = (lane: Lane): Box => ({
		x: LEFT - 10,
		y: bandTop[lane],
		width: width - 2 * (LEFT - 10),
		height: bandHeight[lane]
	});
	return {
		width,
		height: bandTop.target + bandHeight.target + 24 + room,
		bands: { attacker: band('attacker'), target: band('target') },
		heads,
		nodes,
		edges,
		labels
	};
}
