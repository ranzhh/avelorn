<script lang="ts">
	import type { ChargeArc, FightBody } from '$lib/api/client';
	import { TABLE, corners, type Placed as Block, type Point } from '$lib/table';
	import { LANES, type Box, type Lane } from './faces';
	import { BESIDE, CROP, measured, standable, type Field } from './field';
	import { other } from './layout';

	interface Props {
		box: Box;
		/** The charge as last asked for, which the inputs show while a redraw is on its way. */
		charge: NonNullable<FightBody['charge']>;
		/** The blocks as they stand, where the table placed them: the numbers are read off them. */
		field: Field | null;
		open: boolean;
		oncharge: (change: { full_inches?: number; arc?: ChargeArc }) => void;
		/** A block dragged across the crop to stand somewhere new. */
		onmove: (lane: Lane, block: Block) => void;
	}

	let { box, charge, field, open, oncharge, onmove }: Props = $props();

	const ARCS: ChargeArc[] = ['front', 'flank', 'rear'];
	const feet = (edge: number) => Array.from({ length: edge / 12 - 1 }, (_, n) => (n + 1) * 12);

	const outline = (points: Point[]) => points.map(({ x, y }) => `${x},${y}`).join(' ');

	/** The block's diagonals run out past the crop: the lines between its front, flanks and rear. */
	function diagonals(block: Block): [Point, Point][] {
		return corners(block)
			.slice(0, 2)
			.map((corner) => {
				const dx = corner.x - block.x;
				const dy = corner.y - block.y;
				const out = TABLE.width / Math.hypot(dx, dy);
				return [
					{ x: block.x - dx * out, y: block.y - dy * out },
					{ x: block.x + dx * out, y: block.y + dy * out }
				];
			});
	}

	function inches(event: Event & { currentTarget: HTMLInputElement }) {
		const value = event.currentTarget.valueAsNumber;
		if (Number.isInteger(value) && value >= 0) oncharge({ full_inches: value });
	}

	let frame = $state<SVGSVGElement | null>(null);
	/** The block being dragged, and where on it the pointer took hold, in inches from its centre. */
	let held = $state<{ lane: Lane; x: number; y: number } | null>(null);

	function at(event: PointerEvent): Point {
		const point = new DOMPoint(event.clientX, event.clientY);
		return point.matrixTransform(frame!.getScreenCTM()!.inverse());
	}

	function grab(event: PointerEvent, lane: Lane, block: Block) {
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		const point = at(event);
		held = { lane, x: point.x - block.x, y: point.y - block.y };
	}

	function drag(event: PointerEvent) {
		const grip = held;
		if (!grip || !field) return;
		const point = at(event);
		const moved = { ...field.blocks[grip.lane], x: point.x - grip.x, y: point.y - grip.y };
		if (standable(moved, field.blocks[other(grip.lane)], field.crop)) onmove(grip.lane, moved);
	}
</script>

<g class="field" class:open transform="translate({box.x},{box.y})">
	<rect class="card" width={box.width} height={box.height} rx="8" />
	<text class="title" x="12" y="23">Battlefield</text>
	{#if field}
		{@const reading = measured(field.blocks)}
		{@const rows = open
			? { left: BESIDE.x, right: BESIDE.x + BESIDE.width, top: CROP.y + 12 }
			: { left: 12, right: box.width - 12, top: 47 }}
		<text class="small" x={rows.left} y={rows.top}>distance</text>
		<text class="mono" x={rows.right} y={rows.top} text-anchor="end">{reading.full_inches}in</text>
		<text class="small" x={rows.left} y={rows.top + 19}>arc struck</text>
		<text class="mono" x={rows.right} y={rows.top + 19} text-anchor="end">{reading.arc}</text>
		{#if open}
			{@const { crop, blocks } = field}
			<svg
				bind:this={frame}
				class="crop"
				x={CROP.x}
				y={CROP.y}
				width={CROP.width}
				height={CROP.height}
				viewBox="{crop.x} {crop.y} {crop.width} {crop.height}"
			>
				<rect class="off" x={crop.x} y={crop.y} width={crop.width} height={crop.height} />
				<rect class="cloth" width={TABLE.width} height={TABLE.depth} />
				{#each feet(TABLE.width) as x}<line class="foot" x1={x} x2={x} y2={TABLE.depth} />{/each}
				{#each feet(TABLE.depth) as y}<line class="foot" y1={y} x2={TABLE.width} y2={y} />{/each}
				{#each diagonals(blocks.target) as [from, to]}
					<line class="diagonal" x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
				{/each}
				<line
					class="trace"
					x1={blocks.attacker.x}
					y1={blocks.attacker.y}
					x2={blocks.target.x}
					y2={blocks.target.y}
				/>
				{#each LANES as lane}
					{@const points = corners(blocks[lane])}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<g
						class="block {lane}"
						class:held={held?.lane === lane}
						onpointerdown={(event) => grab(event, lane, blocks[lane])}
						onpointermove={drag}
						onpointerup={() => (held = null)}
						onpointercancel={() => (held = null)}
					>
						<polygon points={outline(points)} />
						<line
							class="front"
							x1={points[3].x}
							y1={points[3].y}
							x2={points[0].x}
							y2={points[0].y}
						/>
					</g>
				{/each}
			</svg>
			<rect class="frame" x={CROP.x} y={CROP.y} width={CROP.width} height={CROP.height} />
		{/if}
	{:else}
		<text class="small" x="12" y="45">distance</text>
		<foreignObject x="12" y="51" width={box.width - 24} height="26">
			<label class="inches">
				<input
					class="input"
					type="number"
					min="0"
					value={charge.full_inches}
					oninput={inches}
					aria-label="distance"
				/><span>in</span>
			</label>
		</foreignObject>
		<text class="small" x="12" y="93">arc struck</text>
		<foreignObject x="12" y="99" width={box.width - 24} height="26">
			<select
				class="select"
				value={charge.arc}
				onchange={(event) => oncharge({ arc: event.currentTarget.value as ChargeArc })}
				aria-label="arc struck"
			>
				{#each ARCS as arc}<option value={arc}>{arc}</option>{/each}
			</select>
		</foreignObject>
	{/if}
</g>

<style>
	text {
		fill: var(--ink);
	}
	.mono {
		font: 12px var(--font-mono);
	}
	.small {
		font-size: 11px;
		fill: var(--dim);
	}
	.title {
		font-weight: 600;
	}
	.card {
		fill: var(--panel);
		stroke: #bdbdbd;
	}
	.open .card {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.crop * {
		vector-effect: non-scaling-stroke;
	}
	.off {
		fill: var(--sunken);
	}
	.cloth {
		fill: #fff;
	}
	.foot {
		stroke: #e3e3e3;
	}
	.diagonal {
		stroke: #c4c4c4;
		stroke-dasharray: 3 3;
	}
	.trace {
		stroke: var(--attacker);
		stroke-width: 1.5;
		stroke-dasharray: 4 3;
	}
	.block {
		cursor: grab;
	}
	.block.held {
		cursor: grabbing;
	}
	.block.attacker polygon {
		fill: var(--attacker-tint);
		stroke: var(--attacker);
	}
	.block.target polygon {
		fill: var(--target-tint);
		stroke: var(--target);
	}
	.block .front {
		stroke-width: 3;
	}
	.attacker .front {
		stroke: var(--attacker);
	}
	.target .front {
		stroke: var(--target);
	}
	.frame {
		fill: none;
		stroke: #d4d4d4;
	}
	.inches {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font: 12px var(--font-mono);
	}
	.inches input,
	select {
		width: 100%;
		height: 24px;
		padding: 0 0.4rem;
		font: 12px var(--font-mono);
		background: #fafafa;
	}
	.inches input {
		width: 5rem;
	}
</style>
