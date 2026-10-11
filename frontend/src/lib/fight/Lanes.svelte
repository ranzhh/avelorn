<script lang="ts">
	import { percent } from '$lib/charts/scale';
	import type { ChargeArc, FightBody, FightLanes } from '$lib/api/client';
	import Card from './Card.svelte';
	import { INSET, type Font, type Measure } from './faces';
	import { OUTCOME, draw, type Lane, type Placed } from './layout';

	type Reacting = NonNullable<FightBody['charge']>['reaction'];

	interface Props {
		lanes: FightLanes;
		/** The charge as last asked for, which the battlefield's inputs show while a redraw is on its way. */
		charge: NonNullable<FightBody['charge']> | null;
		selected: string | null;
		/** A node picked, and the side of the drawing away from it, where a panel would not cover it. */
		onselect: (id: string | null, away?: 'left' | 'right') => void;
		/** A unit double-clicked: open its editor. */
		onopen: (lane: Lane) => void;
		oncharge: (change: { full_inches?: number; arc?: ChargeArc; reaction?: Reacting }) => void;
	}

	let { lanes, charge, selected, onselect, onopen, oncharge }: Props = $props();

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

	const drawing = $derived(draw(lanes, measure));

	$effect(() => {
		if (selected && !drawing.nodes.some((node) => node.id === selected)) onselect(null);
	});
	const ARCS: ChargeArc[] = ['front', 'flank', 'rear'];
	const REACTIONS = [
		{ offered: 'hold', value: 'hold', text: 'Hold', name: 'Hold' },
		{ offered: 'stand_and_shoot', value: 'stand-and-shoot', text: 'S&S', name: 'Stand & Shoot' },
		{ offered: 'flee', value: null, text: 'Flee', name: 'Flee' }
	] as const;

	function pick(node: Placed) {
		const centre = node.box.x + node.box.width / 2;
		onselect(node.id, centre > drawing.width / 2 ? 'left' : 'right');
	}

	function key(event: KeyboardEvent, node: Placed) {
		if (event.key !== 'Enter' && event.key !== ' ') return;
		event.preventDefault();
		pick(node);
	}

	function inches(event: Event & { currentTarget: HTMLInputElement }) {
		const value = event.currentTarget.valueAsNumber;
		if (Number.isInteger(value) && value >= 0) oncharge({ full_inches: value });
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
		<text class="label mono {label.tone ?? ''}" x={label.x} y={label.y} text-anchor={label.anchor}
			>{label.text}</text
		>
	{/each}

	{#each drawing.nodes as node}
		{@const { x, y, width, height } = node.box}
		<g
			class="node {node.kind} {'lane' in node ? node.lane : ''}"
			class:on={selected === node.id}
			role="button"
			tabindex="0"
			onclick={(event) => !(event.target as Element).closest('foreignObject') && pick(node)}
			ondblclick={() => node.kind === 'unit' && onopen(node.lane)}
			onkeydown={(event) => key(event, node)}
		>
			{#if 'face' in node}
				<Card face={node.face} box={node.box} tone={node.lane} open={selected === node.id} />
			{:else if node.kind === 'battlefield' && charge}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Battlefield</text>
				<text class="small" x={x + 12} y={y + 45}>distance</text>
				<foreignObject x={x + 12} y={y + 51} width={width - 24} height="26">
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
				<text class="small" x={x + 12} y={y + 93}>arc struck</text>
				<foreignObject x={x + 12} y={y + 99} width={width - 24} height="26">
					<select
						class="select"
						value={charge.arc}
						onchange={(event) => oncharge({ arc: event.currentTarget.value as ChargeArc })}
						aria-label="arc struck"
					>
						{#each ARCS as arc}<option value={arc}>{arc}</option>{/each}
					</select>
				</foreignObject>
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
	.label.attacker {
		fill: var(--attacker);
	}
	.label.target {
		fill: var(--target);
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
	.inches {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font: 12px var(--font-mono);
	}
	.inches input,
	foreignObject select {
		width: 100%;
		height: 24px;
		padding: 0 0.4rem;
		font: 12px var(--font-mono);
		background: #fafafa;
	}
	.inches input {
		width: 5rem;
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
