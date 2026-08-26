<script lang="ts">
	import {
		TABLE,
		angleTo,
		arc,
		base,
		bearing,
		bounds,
		reformed,
		separation,
		snap,
		span,
		within,
		type Placed
	} from '$lib/table';

	interface Props {
		placed: Placed[];
		picked: number | null;
		onpick: (id: number | null) => void;
		onmove: (id: number, x: number, y: number) => void;
		onturn: (id: number, facing: number) => void;
		/** One block dropped onto another: what the first could do to the second. */
		ondrop: (mover: number, target: number) => void;
		/** The block re-formed to a new width in files. */
		onreform: (id: number, frontage: number) => void;
	}

	let { placed, picked, onpick, onmove, onturn, ondrop, onreform }: Props = $props();

	// A foot apart, interior only: the border already draws the table's edge.
	const ruled = (edge: number) =>
		[...Array(Math.floor(edge / 12) - 1).keys()].map((n) => (n + 1) * 12);
	const columns = ruled(TABLE.width);
	const rows = ruled(TABLE.depth);

	let surface = $state<SVGSVGElement | null>(null);

	/**
	 * A drag in flight.
	 *
	 * The block is not moved while dragging: it stays where it stands and a ghost
	 * follows the pointer. Committing early would put the mover on top of its
	 * target, and the gap a charge has to cover would measure zero.
	 */
	let flight = $state<{ id: number; grabX: number; grabY: number; x: number; y: number } | null>(
		null
	);
	let turning = $state<number | null>(null);
	/** A side edge being dragged, and the width it currently reads. */
	let widening = $state<{ id: number; files: number } | null>(null);

	/** The last drag, kept on the table after the pointer lets go. */
	let trace = $state<{
		fromX: number;
		fromY: number;
		toX: number;
		toY: number;
		reading: string;
	} | null>(null);

	// A block arriving or leaving makes the standing trace a lie about the table.
	let counted: number | null = null;
	$effect(() => {
		const now = placed.length;
		if (counted !== null && now !== counted) trace = null;
		counted = now;
	});

	const moving = $derived.by(() => {
		const out = flight;
		return out ? (placed.find((each) => each.id === out.id) ?? null) : null;
	});
	/** Where the ghost stands, as a placed block, so the geometry applies to it. */
	const ghost = $derived.by(() => {
		const out = flight;
		return moving && out ? ({ ...moving, x: out.x, y: out.y } as Placed) : null;
	});
	/** The block the ghost is over, if any. */
	const over = $derived(
		ghost
			? (placed.find((each) => each.id !== ghost.id && separation(ghost, each) === 0) ?? null)
			: null
	);
	/** What the drop would mean, in the numbers the menu will use. */
	const reading = $derived.by(() => {
		if (!moving || !ghost) return null;
		if (over) return `${Math.round(separation(moving, over))}in · ${arc(moving, over)}`;
		return `${Math.round(Math.hypot(ghost.x - moving.x, ghost.y - moving.y))}in`;
	});

	function at(event: PointerEvent) {
		const box = surface!.getBoundingClientRect();
		return {
			x: ((event.clientX - box.left) / box.width) * TABLE.width,
			y: ((event.clientY - box.top) / box.height) * TABLE.depth
		};
	}

	function grab(event: PointerEvent, block: Placed) {
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		const point = at(event);
		trace = null;
		flight = {
			id: block.id,
			grabX: point.x - block.x,
			grabY: point.y - block.y,
			x: block.x,
			y: block.y
		};
		onpick(block.id);
	}

	function grabEdge(event: PointerEvent, block: Placed) {
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		widening = { id: block.id, files: block.block.footprint?.files ?? 1 };
		onpick(block.id);
	}

	function grabHandle(event: PointerEvent, block: Placed) {
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		turning = block.id;
		onpick(block.id);
	}

	function drag(event: PointerEvent) {
		if (flight && moving) {
			const point = at(event);
			const wanted = { ...moving, x: point.x - flight.grabX, y: point.y - flight.grabY };
			// The step is refused rather than the drag: the ghost stops against the
			// edge instead of the pointer running away from it.
			if (within(wanted)) flight = { ...flight, x: wanted.x, y: wanted.y };
			return;
		}
		if (turning !== null) {
			const block = placed.find((each) => each.id === turning);
			if (!block) return;
			const facing = angleTo({ x: block.x, y: block.y }, at(event));
			onturn(block.id, event.shiftKey ? snap(facing) : Math.round(facing));
			return;
		}
		const wide = widening;
		if (wide) {
			const block = placed.find((each) => each.id === wide.id);
			const print = block?.block.footprint;
			if (!block || !print) return;
			const point = at(event);
			const { right } = bearing(block.facing);
			// How far along the block's own width the pointer is from its centre.
			const across = (point.x - block.x) * right.x + (point.y - block.y) * right.y;
			widening = { id: wide.id, files: reformed(print, block.block.size, across) };
		}
	}

	function release() {
		if (flight && moving) {
			const mark = {
				fromX: moving.x,
				fromY: moving.y,
				toX: over ? over.x : flight.x,
				toY: over ? over.y : flight.y,
				reading: reading ?? ''
			};
			// On another block the drop is an action, so the mover stays where it
			// stands and the menu measures from there. Anywhere else it is a move.
			if (over) ondrop(moving.id, over.id);
			else onmove(moving.id, flight.x, flight.y);
			trace = mark;
		}
		const wide = widening;
		if (wide) {
			const block = placed.find((each) => each.id === wide.id);
			if (block && block.block.footprint?.files !== wide.files) {
				onreform(block.id, wide.files);
			}
		}
		flight = null;
		turning = null;
		widening = null;
	}

	/** Where the rotation handle sits: on a stalk off the block's front. */
	function stalk(block: Placed) {
		const footprint = block.block.footprint;
		if (!footprint) return null;
		const reach = span(footprint).depth / 2 + 2.5;
		const radians = (block.facing * Math.PI) / 180;
		return {
			x: block.x + Math.sin(radians) * reach,
			y: block.y - Math.cos(radians) * reach,
			fromX: block.x + Math.sin(radians) * (reach - 2.5),
			fromY: block.y - Math.cos(radians) * (reach - 2.5)
		};
	}
</script>

<svg
	bind:this={surface}
	viewBox="0 0 {TABLE.width} {TABLE.depth}"
	onpointerdown={() => onpick(null)}
	onpointermove={drag}
	onpointerup={release}
	onpointercancel={release}
	role="application"
	aria-label="battle table, {TABLE.width} by {TABLE.depth} inches, {placed.length} blocks"
>
	<defs>
		<marker
			id="arrow"
			viewBox="0 0 8 8"
			refX="6"
			refY="4"
			markerWidth="4"
			markerHeight="4"
			orient="auto"
		>
			<path d="M0,1 L7,4 L0,7 Z" fill="var(--series-1)" />
		</marker>
	</defs>

	<rect class="cloth" x="0" y="0" width={TABLE.width} height={TABLE.depth} />
	{#each columns as inches}
		<line class="foot" x1={inches} y1="0" x2={inches} y2={TABLE.depth} />
	{/each}
	{#each rows as inches}
		<line class="foot" x1="0" y1={inches} x2={TABLE.width} y2={inches} />
	{/each}

	{#each placed as block (block.id)}
		{@const print = block.block.footprint}
		{#if print}
			{@const size = span(print)}
			{@const box = bounds(block)}
			<g
				class="block"
				class:picked={block.id === picked}
				class:origin={flight?.id === block.id}
				class:under={over?.id === block.id}
			>
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<g
					transform="rotate({block.facing} {block.x} {block.y})"
					onpointerdown={(event) => grab(event, block)}
				>
					<rect
						x={block.x - size.width / 2}
						y={block.y - size.depth / 2}
						width={size.width}
						height={size.depth}
					/>
					<line
						class="front"
						x1={block.x - size.width / 2}
						y1={block.y - size.depth / 2}
						x2={block.x + size.width / 2}
						y2={block.y - size.depth / 2}
					/>
					<text x={block.x} y={block.y + 0.6}>{block.block.size}</text>
				</g>

				{#if block.id === picked && !flight}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<g transform="rotate({block.facing} {block.x} {block.y})">
						{#each [-1, 1] as side}
							<rect
								class="edge"
								x={block.x + (side * size.width) / 2 - 0.5}
								y={block.y - 1}
								width="1"
								height="2"
								onpointerdown={(event) => grabEdge(event, block)}
							/>
						{/each}
					</g>
					{@const handle = stalk(block)}
					{#if handle}
						<line class="tether" x1={handle.fromX} y1={handle.fromY} x2={handle.x} y2={handle.y} />
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<circle
							class="handle"
							cx={handle.x}
							cy={handle.y}
							r="1.1"
							onpointerdown={(event) => grabHandle(event, block)}
						/>
					{/if}
					<rect
						class="halo"
						x={box.left - 0.4}
						y={box.top - 0.4}
						width={box.width + 0.8}
						height={box.height + 0.8}
					/>
				{/if}
			</g>
		{/if}
	{/each}

	{#if widening !== null}
		{@const reform = widening}
		{@const block = placed.find((each) => each.id === reform.id)}
		{#if block}
			{@const print = block.block.footprint}
			{#if print}
				{@const ranks = Math.ceil(block.block.size / reform.files)}
				{@const cell = base(print)}
				{@const wide = reform.files * cell.width}
				{@const deep = ranks * cell.depth}
				<g class="ghost" transform="rotate({block.facing} {block.x} {block.y})">
					<rect x={block.x - wide / 2} y={block.y - deep / 2} width={wide} height={deep} />
				</g>
				<text class="reading" x={block.x} y={block.y - deep / 2 - 1}>
					{reform.files}×{ranks}
				</text>
			{/if}
		{/if}
	{/if}

	{#if trace && !flight}
		<g class="trace">
			<line
				class="path"
				x1={trace.fromX}
				y1={trace.fromY}
				x2={trace.toX}
				y2={trace.toY}
				marker-end="url(#arrow)"
			/>
			{#if trace.reading}
				<text
					class="reading"
					x={(trace.fromX + trace.toX) / 2}
					y={(trace.fromY + trace.toY) / 2 - 1}
				>
					{trace.reading}
				</text>
			{/if}
		</g>
	{/if}

	{#if ghost && moving}
		{@const print = ghost.block.footprint}
		{#if print}
			{@const size = span(print)}
			<line
				class="path"
				x1={moving.x}
				y1={moving.y}
				x2={over ? over.x : ghost.x}
				y2={over ? over.y : ghost.y}
				marker-end="url(#arrow)"
			/>
			<g class="ghost" transform="rotate({ghost.facing} {ghost.x} {ghost.y})">
				<rect
					x={ghost.x - size.width / 2}
					y={ghost.y - size.depth / 2}
					width={size.width}
					height={size.depth}
				/>
				<line
					class="front"
					x1={ghost.x - size.width / 2}
					y1={ghost.y - size.depth / 2}
					x2={ghost.x + size.width / 2}
					y2={ghost.y - size.depth / 2}
				/>
			</g>
			{#if reading}
				<text class="reading" x={(moving.x + ghost.x) / 2} y={(moving.y + ghost.y) / 2 - 1}>
					{reading}
				</text>
			{/if}
		{/if}
	{/if}
</svg>

<style>
	svg {
		display: block;
		width: 100%;
		background: var(--sunken);
		border: 1px solid var(--line);
		border-radius: var(--radius-md);
		touch-action: none;
	}

	.cloth {
		fill: var(--sunken);
	}

	.foot {
		stroke: var(--line);
		stroke-width: 0.06;
	}

	.block rect {
		fill: color-mix(in oklab, var(--series-1) 20%, var(--sunken));
		stroke: color-mix(in oklab, var(--series-1) 45%, var(--sunken));
		stroke-width: 0.08;
		cursor: grab;
	}

	.block .front {
		stroke: color-mix(in oklab, var(--series-1) 70%, var(--sunken));
		stroke-width: 0.35;
	}

	.block.picked rect {
		fill: color-mix(in oklab, var(--series-1) 32%, var(--sunken));
		stroke: var(--series-1);
		stroke-width: 0.18;
	}

	.block.picked .front {
		stroke: var(--series-1);
	}

	/* Where the block still stands while its ghost is out. */
	.block.origin rect,
	.block.origin .front {
		opacity: 0.45;
		cursor: grabbing;
	}

	.block.under rect {
		fill: color-mix(in oklab, var(--series-2) 30%, var(--sunken));
		stroke: var(--series-2);
		stroke-width: 0.2;
	}

	.block.under .front {
		stroke: var(--series-2);
	}

	.block text {
		font: 1.6px var(--font-mono);
		text-anchor: middle;
		fill: var(--ink);
		pointer-events: none;
	}

	.ghost {
		pointer-events: none;
	}

	.ghost rect {
		fill: none;
		stroke: var(--series-1);
		stroke-width: 0.12;
		stroke-dasharray: 0.6 0.4;
	}

	.ghost .front {
		stroke: var(--series-1);
		stroke-width: 0.3;
	}

	.path {
		stroke: var(--series-1);
		stroke-width: 0.12;
		pointer-events: none;
	}

	/* The drag that has finished: quieter than the one in hand. */
	.trace {
		opacity: 0.55;
		pointer-events: none;
	}

	.trace .path {
		stroke-dasharray: 0.8 0.5;
	}

	.reading {
		font: 1.8px var(--font-mono);
		text-anchor: middle;
		fill: var(--ink);
		paint-order: stroke;
		stroke: var(--sunken);
		stroke-width: 0.7;
		pointer-events: none;
	}

	.halo {
		fill: none;
		stroke: var(--series-1);
		stroke-width: 0.06;
		stroke-dasharray: 0.5 0.4;
		pointer-events: none;
		opacity: 0.7;
	}

	.tether {
		stroke: var(--series-1);
		stroke-width: 0.09;
		pointer-events: none;
	}

	.handle {
		fill: var(--sunken);
		stroke: var(--series-1);
		stroke-width: 0.18;
		cursor: grab;
	}

	.handle:hover {
		fill: var(--series-1);
	}

	.edge {
		fill: var(--sunken);
		stroke: var(--series-1);
		stroke-width: 0.15;
		cursor: ew-resize;
	}

	.edge:hover {
		fill: var(--series-1);
	}
</style>
