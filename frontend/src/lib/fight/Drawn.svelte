<script lang="ts">
	import type { Snippet } from 'svelte';
	import Card from './Card.svelte';
	import { OUTCOME, type Drawing, type Lane, type Placed } from './layout';

	interface Props {
		drawing: Drawing;
		label: string;
		/** The node showing its whole face, if any. */
		open: string | null;
		ontoggle: (id: string) => void;
		/** A unit double-clicked. */
		onedit?: (lane: Lane) => void;
		/** What a node draws over or instead of its card. */
		extra?: Snippet<[Placed]>;
	}

	let { drawing, label, open, ontoggle, onedit, extra }: Props = $props();

	function click(event: MouseEvent, node: Placed) {
		if (event.detail > 1 || (event.target as Element).closest('foreignObject, .crop')) return;
		ontoggle(node.id);
	}

	function key(event: KeyboardEvent, node: Placed) {
		if (event.target !== event.currentTarget) return;
		if (event.key !== 'Enter' && event.key !== ' ') return;
		event.preventDefault();
		ontoggle(node.id);
	}
</script>

<svg
	class="lanes"
	viewBox="0 0 {drawing.width} {drawing.height}"
	width={drawing.width}
	height={drawing.height}
	role="group"
	aria-label={label}
>
	<defs>
		{#each ['ink', 'attacker', 'target'] as tone}
			<marker
				id="head-{tone}"
				class={tone}
				viewBox="0 0 10 10"
				refX="9"
				refY="5"
				markerWidth="7"
				markerHeight="7"
				orient="auto-start-reverse"
			>
				<path d="M0,0 L10,5 L0,10 z" />
			</marker>
		{/each}
	</defs>

	<line class="rule" x1="30" y1="46" x2={drawing.width - 30} y2="46" />
	{#each drawing.heads as head}
		<text class="small head" x={head.x} y="38">{head.text}</text>
	{/each}
	{#each Object.entries(drawing.bands) as [lane, band]}
		<rect class="band {lane}" x={band.x} y={band.y} width={band.width} height={band.height} />
	{/each}

	{#each drawing.edges as edge}
		<path
			class="edge {edge.tone ?? 'ink'}"
			d={edge.d}
			marker-end={edge.bare ? undefined : `url(#head-${edge.tone ?? 'ink'})`}
		/>
	{/each}
	{#each drawing.labels as label}
		<text class="label mono" x={label.x} y={label.y} text-anchor={label.anchor}>{label.text}</text>
	{/each}

	{#each drawing.nodes as node}
		{@const { x, y, width, height } = node.box}
		<g
			class="node {node.kind} {'lane' in node ? node.lane : ''}"
			class:on={open === node.id}
			role="button"
			tabindex="0"
			aria-expanded={open === node.id}
			onclick={(event) => click(event, node)}
			ondblclick={() => node.kind === 'unit' && onedit?.(node.lane)}
			onkeydown={(event) => key(event, node)}
		>
			{#if 'face' in node}
				<Card face={node.face} box={node.box} tone={node.lane} open={open === node.id} />
			{:else if node.kind === 'short'}
				<rect class="card short" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Falls short</text>
			{:else if node.kind === 'outcome'}
				<rect class="terminal" {x} {y} {width} {height} rx="6" />
				<rect
					class="fill"
					class:worst={node.worst}
					{x}
					{y}
					width={Math.max(node.p * OUTCOME.width, 2)}
					{height}
					rx="3"
				/>
				<text x={x + 10} y={y + 17}>{node.name}</text>
				<text class="mono" x={x + width - 8} y={y + 17} text-anchor="end">{node.text}</text>
			{/if}
			{@render extra?.(node)}
		</g>
	{/each}
</svg>

<style>
	.lanes {
		--attacker: var(--series-1);
		--target: var(--series-2);
		--attacker-band: color-mix(in srgb, var(--series-1) 7%, var(--plane));
		--target-band: color-mix(in srgb, var(--series-2) 7%, var(--plane));
		--attacker-tint: color-mix(in srgb, var(--series-1) 16%, var(--plane));
		--target-tint: color-mix(in srgb, var(--series-2) 16%, var(--plane));
		--short: #cbcbcb;
		display: block;
		max-width: none;
		font: 13px var(--font-sans);
		user-select: none;
	}
	text {
		fill: var(--ink);
	}
	.mono {
		font: 12px var(--font-mono);
		white-space: pre;
	}
	.small {
		font-size: 11px;
		fill: var(--dim);
	}
	.head {
		text-anchor: middle;
	}
	.title {
		font-weight: 600;
	}
	.rule {
		stroke: #ddd;
	}
	.band.attacker {
		fill: var(--attacker-band);
	}
	.band.target {
		fill: var(--target-band);
	}
	.edge {
		fill: none;
		stroke: #444;
		stroke-width: 1.5;
	}
	.edge.attacker {
		stroke: var(--attacker);
	}
	.edge.target {
		stroke: var(--target);
	}
	marker path {
		fill: #444;
	}
	marker.attacker path {
		fill: var(--attacker);
	}
	marker.target path {
		fill: var(--target);
	}
	.label {
		font-size: 11px;
		fill: #444;
	}
	.node {
		cursor: pointer;
		outline: none;
	}
	.card,
	.terminal {
		fill: var(--panel);
		stroke: #bdbdbd;
	}
	.card.short {
		stroke: #9a9a9a;
		stroke-dasharray: 4 3;
	}
	.node.on :global(.card),
	.node.on .terminal,
	.node:focus-visible :global(.card),
	.node:focus-visible :global(.pill) {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.attacker .fill {
		fill: var(--attacker-tint);
	}
	.target .fill {
		fill: var(--target-tint);
	}
	.target .fill.worst {
		fill: color-mix(in srgb, var(--series-2) 32%, var(--plane));
	}
	.attacker .fill.worst {
		fill: color-mix(in srgb, var(--series-1) 32%, var(--plane));
	}
</style>
