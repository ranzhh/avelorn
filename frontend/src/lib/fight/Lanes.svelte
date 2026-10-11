<script lang="ts">
	import type { Snippet } from 'svelte';
	import { percent } from '$lib/charts/scale';
	import type { ChargeArc, FightBody, FightLanes } from '$lib/api/client';
	import type { Placed as Block } from '$lib/table';
	import Battlefield from './Battlefield.svelte';
	import Card from './Card.svelte';
	import type { Field } from './field';
	import { INSET, type Font, type Measure } from './faces';
	import { OUTCOME, draw, type Lane, type Placed } from './layout';

	type Reacting = NonNullable<FightBody['charge']>['reaction'];

	interface Props {
		lanes: FightLanes;
		/** The charge as last asked for, which the battlefield's inputs show while a redraw is on its way. */
		charge: NonNullable<FightBody['charge']> | null;
		/** The blocks the battlefield measures, where the table placed them. */
		field: Field | null;
		/** The node showing its whole face, if any. */
		open: string | null;
		/** The unit edited in place, if any, and the controls that edit it. */
		editing: Lane | null;
		editor: Snippet<[Lane]>;
		ontoggle: (id: string) => void;
		/** A unit double-clicked: edit it. */
		onedit: (lane: Lane) => void;
		oncharge: (change: { full_inches?: number; arc?: ChargeArc; reaction?: Reacting }) => void;
		/** A block dragged across the battlefield's crop. */
		onmove: (lane: Lane, block: Block) => void;
	}

	let { lanes, charge, field, open, editing, editor, ontoggle, onedit, oncharge, onmove }: Props =
		$props();

	const FONTS: Record<Font, string> = {
		title: '600 13px system-ui, sans-serif',
		text: '13px system-ui, sans-serif',
		small: '11px system-ui, sans-serif',
		chip: '11px system-ui, sans-serif',
		mono: '12px ui-monospace, Menlo, Consolas, monospace'
	};
	const context = document.createElement('canvas').getContext('2d')!;
	const measure: Measure = (text, font) => {
		context.font = FONTS[font];
		return Math.ceil(context.measureText(text).width);
	};

	let editorHeight = $state(160);
	const drawing = $derived(
		draw(lanes, measure, open, editing && { lane: editing, height: editorHeight }, !!field)
	);

	$effect(() => {
		if (open && !drawing.nodes.some((node) => node.id === open)) ontoggle(open);
	});
	const REACTIONS = [
		{ offered: 'hold', value: 'hold', text: 'Hold', name: 'Hold' },
		{ offered: 'stand_and_shoot', value: 'stand-and-shoot', text: 'S&S', name: 'Stand & Shoot' },
		{ offered: 'flee', value: null, text: 'Flee', name: 'Flee' }
	] as const;

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
	aria-label="{lanes.units.attacker.name} against {lanes.units.target.name}"
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
			ondblclick={() => node.kind === 'unit' && onedit(node.lane)}
			onkeydown={(event) => key(event, node)}
		>
			{#if 'face' in node}
				<Card face={node.face} box={node.box} tone={node.lane} open={open === node.id} />
				{#if node.kind === 'unit' && node.face.slot}
					{@const slot = node.face.slot}
					<foreignObject x={x + slot.x} y={y + slot.y} width={slot.width} height={slot.height}>
						<div class="editor" bind:offsetHeight={editorHeight}>{@render editor(node.lane)}</div>
					</foreignObject>
				{/if}
			{:else if node.kind === 'battlefield' && charge}
				<Battlefield box={node.box} {charge} {field} open={open === node.id} {oncharge} {onmove} />
			{:else if node.kind === 'reaction' && lanes.reaction}
				{@const reaction = lanes.reaction}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<rect class="spine" {x} {y} width="4" {height} />
				<text class="title" x={x + INSET} y={y + 23}>Reaction</text>
				<foreignObject x={x + INSET} y={y + 36} width={width - INSET - 8} height="28">
					<div class="segments" role="radiogroup" aria-label="reaction">
						{#each REACTIONS as choice}
							<button
								role="radio"
								aria-checked={reaction.chosen === choice.value}
								title={choice.name}
								class:on={reaction.chosen === choice.value}
								disabled={!reaction.offered[choice.offered] || choice.value === null}
								onclick={() => choice.value && oncharge({ reaction: choice.value })}
								>{choice.text}</button
							>
						{/each}
					</div>
				</foreignObject>
			{:else if node.kind === 'short'}
				<rect class="card short" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Falls short</text>
			{:else if node.kind === 'outcome'}
				<rect class="terminal" {x} {y} {width} {height} rx="6" />
				<rect
					class="fill"
					class:worst={node.name === 'Break'}
					{x}
					{y}
					width={Math.max(node.p * OUTCOME.width, 2)}
					{height}
					rx="3"
				/>
				<text x={x + 10} y={y + 17}>{node.name}</text>
				<text class="mono" x={x + width - 8} y={y + 17} text-anchor="end">{percent(node.p)}</text>
			{/if}
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
	.node.on .card,
	.node.on .terminal,
	.node:focus-visible :global(.card),
	.node:focus-visible :global(.pill) {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.reaction .spine {
		fill: var(--target);
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
	.editor {
		display: grid;
		gap: var(--space-2);
		cursor: auto;
	}
	.segments {
		display: flex;
		gap: 2px;
	}
	.segments button {
		height: 26px;
		padding: 0 0.6rem;
		font-size: 12px;
		cursor: pointer;
	}
	.segments button.on {
		color: var(--on-accent);
		background: var(--target);
		border-color: var(--target);
	}
	.segments button:disabled {
		color: #b0b0b0;
		background: #f4f4f4;
		border-color: #d6d6d6;
		cursor: default;
	}
</style>
