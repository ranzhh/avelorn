<script lang="ts">
	import { TABLE, extent, type Placed } from '$lib/table';

	interface Props {
		placed: Placed[];
		picked: number | null;
		/** A costed block waiting for somewhere to stand; the surface takes a placing click. */
		placing: boolean;
		onplace: (x: number, y: number) => void;
		onpick: (id: number | null) => void;
	}

	let { placed, picked, placing, onplace, onpick }: Props = $props();

	// A foot apart, interior only: the border already draws the table's edge.
	const ruled = (span: number) =>
		[...Array(Math.floor(span / 12) - 1).keys()].map((n) => (n + 1) * 12);
	const columns = ruled(TABLE.width);
	const rows = ruled(TABLE.depth);

	function onSurface(event: MouseEvent) {
		const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
		const x = ((event.clientX - box.left) / box.width) * TABLE.width;
		const y = ((event.clientY - box.top) / box.height) * TABLE.depth;
		if (placing) onplace(x, y);
		else onpick(null);
	}

	/** The front edge, as two points, given the facing. */
	function front(block: Placed) {
		const box = extent(block);
		switch (block.facing) {
			case 0:
				return { x1: box.left, y1: box.top, x2: box.right, y2: box.top };
			case 180:
				return { x1: box.left, y1: box.bottom, x2: box.right, y2: box.bottom };
			case 90:
				return { x1: box.right, y1: box.top, x2: box.right, y2: box.bottom };
			case 270:
				return { x1: box.left, y1: box.top, x2: box.left, y2: box.bottom };
		}
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions, a11y_no_noninteractive_element_interactions -->
<svg
	viewBox="0 0 {TABLE.width} {TABLE.depth}"
	class:placing
	onclick={onSurface}
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
		{@const box = extent(block)}
		{@const edge = front(block)}
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<g
			class="block"
			class:picked={block.id === picked}
			onclick={(event) => {
				event.stopPropagation();
				onpick(block.id === picked ? null : block.id);
			}}
		>
			<rect x={box.left} y={box.top} width={box.width} height={box.height} />
			<line class="front" x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2} />
			<text x={block.x} y={block.y + 0.6}>{block.block.size}</text>
		</g>
	{/each}
</svg>

<style>
	svg {
		display: block;
		width: 100%;
		background: var(--sunken);
		border: 1px solid var(--line);
		border-radius: var(--radius-md);
	}

	svg.placing {
		cursor: crosshair;
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
		cursor: pointer;
	}

	.block .front {
		stroke: color-mix(in oklab, var(--series-1) 70%, var(--sunken));
		stroke-width: 0.35;
	}

	.block.picked rect {
		fill: color-mix(in oklab, var(--series-1) 32%, var(--sunken));
		stroke: var(--series-1);
		stroke-width: 0.22;
	}

	.block.picked .front {
		stroke: var(--series-1);
	}

	.block text {
		font: 1.6px var(--font-mono);
		text-anchor: middle;
		fill: var(--ink);
		pointer-events: none;
	}
</style>
