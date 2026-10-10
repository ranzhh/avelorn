<script lang="ts">
	import {
		TABLE,
		angleTo,
		arc,
		base,
		bearing,
		legend,
		pivot,
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
		/** A datasheet dragged in from the panel and dropped on the table. */
		ondropunit: (unit: string, size: number, x: number, y: number) => void;
		/** A block double-clicked: open its size and options. */
		onedit: (id: number) => void;
	}

	let { placed, picked, onpick, onmove, onturn, ondrop, onreform, ondropunit, onedit }: Props =
		$props();

	/** A datasheet being dragged in from the panel, over the table. */
	let inbound = $state(false);

	function carried(event: DragEvent): [string, number] | null {
		const payload = event.dataTransfer?.getData('application/avelorn-unit');
		if (!payload) return null;
		const [unit, size] = payload.split(':');
		return unit ? [unit, Number(size) || 1] : null;
	}

	function admit(event: DragEvent) {
		if (!event.dataTransfer?.types.includes('application/avelorn-unit')) return;
		event.preventDefault();
		inbound = true;
	}

	function land(event: DragEvent) {
		event.preventDefault();
		inbound = false;
		const held = carried(event);
		if (!held) return;
		const box = surface!.getBoundingClientRect();
		ondropunit(
			held[0],
			held[1],
			((event.clientX - box.left) / box.width) * TABLE.width,
			((event.clientY - box.top) / box.height) * TABLE.depth
		);
	}

	// A foot apart, interior only: the border already draws the table's edge.
	const ruled = (edge: number) =>
		[...Array(Math.floor(edge / 12) - 1).keys()].map((n) => (n + 1) * 12);
	const columns = ruled(TABLE.width);
	const rows = ruled(TABLE.depth);

	let surface = $state<SVGSVGElement | null>(null);

	/** Screen pixels to the inch, so handles and readings keep one size however large the table is drawn. */
	let perInch = $state(12);
	$effect(() => {
		const drawn = surface;
		if (!drawn) return;
		const watch = new ResizeObserver(() => {
			const width = drawn.getBoundingClientRect().width;
			if (width > 0) perInch = width / TABLE.width;
		});
		watch.observe(drawn);
		return () => watch.disconnect();
	});
	const px = $derived(1 / perInch);
	const KNOB = 10;

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
	/** A block being turned, how far from its facing the handle was grabbed, and off which edge. */
	let turning = $state<{ id: number; offset: number; side: number } | null>(null);
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

	const chosen = $derived(placed.find((each) => each.id === picked) ?? null);
	const knob = $derived(
		chosen?.block.footprint
			? pivot(
					chosen,
					placed,
					KNOB * px,
					2 * KNOB * px,
					turning?.id === chosen.id ? turning.side : undefined
				)
			: null
	);

	const moving = $derived.by(() => {
		const out = flight;
		return out ? (placed.find((each) => each.id === out.id) ?? null) : null;
	});
	/** Where the ghost stands, as a placed block, so the geometry applies to it. */
	const ghost = $derived.by(() => {
		const out = flight;
		return moving && out ? ({ ...moving, x: out.x, y: out.y } as Placed) : null;
	});
	/** How far the ghost has been carried; a press that has not left the block is a click. */
	const travelled = $derived(
		ghost && moving ? Math.hypot(ghost.x - moving.x, ghost.y - moving.y) : 0
	);
	const carrying = $derived(travelled > 3 * px);
	/** The block the ghost is over, if any. */
	const over = $derived(
		ghost && carrying
			? (placed.find((each) => each.id !== ghost.id && separation(ghost, each) === 0) ?? null)
			: null
	);
	/** What the drop would mean, in the numbers the menu will use. */
	const reading = $derived.by(() => {
		if (!moving || !ghost) return null;
		if (over) return `${Math.round(separation(moving, over))}in · ${arc(moving, over)}`;
		return `${Math.round(travelled)}in`;
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
		turning = {
			id: block.id,
			offset: angleTo(block, at(event)) - block.facing,
			side: knob?.side ?? 0
		};
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
		const turn = turning;
		if (turn) {
			const block = placed.find((each) => each.id === turn.id);
			if (!block) return;
			const facing = (angleTo(block, at(event)) - turn.offset + 360) % 360;
			onturn(block.id, event.shiftKey ? snap(facing) : Math.round(facing) % 360);
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
			else if (carrying) onmove(moving.id, flight.x, flight.y);
			if (carrying) trace = mark;
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
</script>

<svg
	bind:this={surface}
	viewBox="0 0 {TABLE.width} {TABLE.depth}"
	onpointerdown={() => onpick(null)}
	onpointermove={drag}
	onpointerup={release}
	onpointercancel={release}
	ondragover={admit}
	ondragleave={() => (inbound = false)}
	ondrop={land}
	class:inbound
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

	{#if chosen && knob && !flight}
		{@const print = chosen.block.footprint}
		{#if print}
			{@const size = span(print)}
			{@const pad = 4 * px}
			{@const reach = Math.max(size.depth, 24 * px)}
			<g class="chrome" transform="rotate({chosen.facing} {chosen.x} {chosen.y})">
				<rect
					class="halo"
					x={chosen.x - size.width / 2 - pad}
					y={chosen.y - size.depth / 2 - pad}
					width={size.width + 2 * pad}
					height={size.depth + 2 * pad}
				/>
				{#if chosen.block.size > 1}
					{#each [-1, 1] as side}
						{@const edge = chosen.x + (side * size.width) / 2}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<g class="edge" onpointerdown={(event) => grabEdge(event, chosen)}>
							<rect
								class="reach"
								x={side < 0 ? edge - 16 * px : edge}
								y={chosen.y - reach / 2}
								width={16 * px}
								height={reach}
							/>
							<rect
								class="grip"
								x={edge + side * pad - 3 * px}
								y={chosen.y - size.depth / 2 - pad}
								width={6 * px}
								height={size.depth + 2 * pad}
								rx={3 * px}
							/>
						</g>
					{/each}
				{/if}
			</g>
		{/if}
	{/if}

	{#each placed as block (block.id)}
		{@const print = block.block.footprint}
		{#if print}
			{@const size = span(print)}
			{@const label = legend(block)}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<g
				class="block"
				class:picked={block.id === picked}
				class:origin={flight?.id === block.id && carrying}
				class:under={over?.id === block.id}
				onpointerdown={(event) => grab(event, block)}
				ondblclick={() => onedit(block.id)}
			>
				<g transform="rotate({block.facing} {block.x} {block.y})">
					<rect
						class="footprint"
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
				</g>
				<text class="mark" x={block.x} y={block.y} font-size={label.size}>
					{block.mark}{#if label.count}<tspan class="count" dx={label.size * 0.3}
							>{block.block.size}</tspan
						>{/if}
				</text>
			</g>
		{/if}
	{/each}

	{#if chosen && knob && !flight}
		<g class="chrome">
			<line class="tether" x1={knob.from.x} y1={knob.from.y} x2={knob.at.x} y2={knob.at.y} />
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<circle
				class="handle"
				cx={knob.at.x}
				cy={knob.at.y}
				r={KNOB * px}
				onpointerdown={(event) => grabHandle(event, chosen)}
			/>
		</g>
	{/if}

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
				<text class="reading" x={block.x} y={block.y - deep / 2 - 10 * px} font-size={12 * px}>
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
					y={(trace.fromY + trace.toY) / 2 - 10 * px}
					font-size={12 * px}
				>
					{trace.reading}
				</text>
			{/if}
		</g>
	{/if}

	{#if ghost && moving && carrying}
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
				<text
					class="reading"
					x={(moving.x + ghost.x) / 2}
					y={(moving.y + ghost.y) / 2 - 10 * px}
					font-size={12 * px}
				>
					{reading}
				</text>
			{/if}
		{/if}
	{/if}
</svg>
