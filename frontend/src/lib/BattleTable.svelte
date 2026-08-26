<script lang="ts">
	import { TABLE, angleTo, bounds, separation, snap, span, within, type Placed } from '$lib/table';

	interface Props {
		placed: Placed[];
		picked: number | null;
		onpick: (id: number | null) => void;
		onmove: (id: number, x: number, y: number) => void;
		onturn: (id: number, facing: number) => void;
		/** One block dropped onto another: what the first could do to the second. */
		ondrop: (mover: number, target: number) => void;
	}

	let { placed, picked, onpick, onmove, onturn, ondrop }: Props = $props();

	// A foot apart, interior only: the border already draws the table's edge.
	const ruled = (edge: number) =>
		[...Array(Math.floor(edge / 12) - 1).keys()].map((n) => (n + 1) * 12);
	const columns = ruled(TABLE.width);
	const rows = ruled(TABLE.depth);

	let surface = $state<SVGSVGElement | null>(null);

	// What the pointer is doing, and to which block.
	let dragging = $state<{ id: number; grabX: number; grabY: number } | null>(null);
	let turning = $state<number | null>(null);
	// The block the dragged one is currently on top of.
	let over = $state<number | null>(null);

	/** The pointer's position in table inches. */
	function at(event: PointerEvent) {
		const box = surface!.getBoundingClientRect();
		return {
			x: ((event.clientX - box.left) / box.width) * TABLE.width,
			y: ((event.clientY - box.top) / box.height) * TABLE.depth
		};
	}

	const held = (id: number) => placed.find((each) => each.id === id);

	function grab(event: PointerEvent, block: Placed) {
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		const point = at(event);
		dragging = { id: block.id, grabX: point.x - block.x, grabY: point.y - block.y };
		onpick(block.id);
	}

	function grabHandle(event: PointerEvent, block: Placed) {
		event.stopPropagation();
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
		turning = block.id;
		onpick(block.id);
	}

	function drag(event: PointerEvent) {
		if (dragging) {
			const block = held(dragging.id);
			if (!block) return;
			const point = at(event);
			const moved = { ...block, x: point.x - dragging.grabX, y: point.y - dragging.grabY };
			// The step is refused rather than the drag: a block stops against the
			// edge instead of the pointer running away from it.
			if (within(moved)) {
				onmove(block.id, moved.x, moved.y);
				const landed = { ...moved };
				over =
					placed.find((other) => other.id !== block.id && separation(landed, other) === 0)?.id ??
					null;
			}
			return;
		}
		if (turning !== null) {
			const block = held(turning);
			if (!block) return;
			const facing = angleTo({ x: block.x, y: block.y }, at(event));
			onturn(block.id, event.shiftKey ? snap(facing) : Math.round(facing));
		}
	}

	function release() {
		if (dragging && over !== null) ondrop(dragging.id, over);
		dragging = null;
		turning = null;
		over = null;
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
				class:busy={dragging?.id === block.id || turning === block.id}
				class:under={over === block.id}
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

				{#if block.id === picked}
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

	.block.busy rect {
		cursor: grabbing;
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
</style>
