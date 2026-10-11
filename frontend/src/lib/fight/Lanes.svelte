<script lang="ts">
	import { percent } from '$lib/charts/scale';
	import type { FightLanes } from '$lib/api/client';
	import {
		INSET,
		OUTCOME,
		STRIKE,
		commanded,
		count,
		draw,
		formation,
		mean,
		needs,
		signed,
		type Font,
		type Measure,
		type Placed
	} from './layout';

	interface Props {
		lanes: FightLanes;
		selected: string | null;
		/** A node picked, and the side of the drawing away from it, where a panel would not cover it. */
		onselect: (id: string, away: 'left' | 'right') => void;
	}

	let { lanes, selected, onselect }: Props = $props();

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
	const REACTIONS = [
		{ offered: 'hold', value: 'hold', text: 'Hold', width: 44 },
		{ offered: 'stand_and_shoot', value: 'stand-and-shoot', text: 'S&S', width: 52 },
		{ offered: 'flee', value: null, text: 'Flee', width: 44 }
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
			onclick={() => pick(node)}
			onkeydown={(event) => key(event, node)}
		>
			{#if node.kind === 'unit'}
				{@const unit = node.unit}
				{@const top = y + node.glyph}
				{@const ranks = Math.ceil(unit.size / unit.frontage)}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<rect class="spine" {x} {y} width="4" {height} />
				<text class="title" x={x + INSET} y={y + 23}>{unit.name}</text>
				<text class="mono" x={x + width - INSET} y={y + 23} text-anchor="end">×{unit.size}</text>
				{#each node.chips as chip}
					<rect
						class="chip"
						x={x + chip.x}
						y={y + chip.y}
						width={chip.width}
						height={chip.height}
						rx="10"
					/>
					<text class="chip-text" x={x + chip.x + chip.width / 2} y={y + chip.y + 14}
						>{chip.text}</text
					>
				{/each}
				{#each formation(unit.size, unit.frontage, commanded(unit)) as model}
					<rect
						class="model"
						class:command={model.command}
						x={x + INSET + model.file * node.pitch}
						y={top + model.rank * node.pitch}
						width={node.pitch - 3}
						height={node.pitch - 3}
					>
						{#if model.command}<title>{model.command}</title>{/if}
					</rect>
				{/each}
				<text class="mono" x={x + width - INSET} y={top + ranks * node.pitch - 5} text-anchor="end"
					>{unit.frontage} × {unit.ranks}</text
				>
			{:else if node.kind === 'battlefield' && lanes.battlefield}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Battlefield</text>
				<text class="small" x={x + 12} y={y + 45}>distance</text>
				<rect class="field" x={x + 12} y={y + 51} width={width - 24} height="24" rx="4" />
				<text class="mono" x={x + 22} y={y + 68}>{lanes.battlefield.distance}in</text>
				<text class="small" x={x + 12} y={y + 93}>arc struck</text>
				<rect class="field" x={x + 12} y={y + 99} width={width - 24} height="24" rx="4" />
				<text class="mono" x={x + 22} y={y + 116}>{lanes.battlefield.arc}</text>
			{:else if node.kind === 'charge' && lanes.charge}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<rect class="spine" {x} {y} width="4" {height} />
				<text class="title" x={x + INSET} y={y + 23}>Charge</text>
				<text class="mono" x={x + INSET} y={y + 43}
					>{lanes.charge.distance}in · {lanes.charge.arc}</text
				>
				<text class="mono" x={x + INSET} y={y + 61}>roll ≥ {lanes.charge.distance}in</text>
			{:else if node.kind === 'reaction' && lanes.reaction}
				{@const reaction = lanes.reaction}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<rect class="spine" {x} {y} width="4" {height} />
				<text class="title" x={x + INSET} y={y + 23}>Reaction</text>
				{#each REACTIONS as choice, index}
					{@const left =
						x + INSET + REACTIONS.slice(0, index).reduce((sum, each) => sum + each.width + 2, 0)}
					<g
						class="segment"
						class:on={reaction.chosen === choice.value}
						class:off={!reaction.offered[choice.offered]}
					>
						<rect x={left} y={y + 36} width={choice.width} height="26" rx="4" />
						<text x={left + choice.width / 2} y={y + 53}>{choice.text}</text>
					</g>
				{/each}
			{:else if node.kind === 'short'}
				<rect class="card short" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Falls short</text>
			{:else if node.kind === 'volley' && lanes.volley}
				{@const [rolls, saves] = needs(lanes.volley.needed)}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<path
					class="header"
					d="M{x},{y + 8} a8,8 0 0 1 8,-8 h{width - 16} a8,8 0 0 1 8,8 v{STRIKE.header -
						8} h{-width} z"
				/>
				<text class="title" x={x + 12} y={y + 18}>{lanes.units.target.name}</text>
				<text x={x + 12} y={y + 46}>{lanes.volley.shots} shots</text>
				<text class="mono" x={x + 12} y={y + 65}>{rolls}</text>
				<text class="mono" x={x + 12} y={y + 82}>{saves}</text>
			{:else if node.kind === 'strike'}
				{@const strike = node.strike}
				{@const [rolls, saves] = needs(strike.needed)}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<path
					class="header"
					d="M{x},{y + 8} a8,8 0 0 1 8,-8 h{width - 16} a8,8 0 0 1 8,8 v{STRIKE.header -
						8} h{-width} z"
				/>
				<text class="title" x={x + 12} y={y + 18}>{node.title}</text>
				<text x={x + 12} y={y + 46}>{count(strike.attacks)} attacks</text>
				<text class="mono" x={x + 12} y={y + 65}>{rolls}</text>
				<text class="mono" x={x + 12} y={y + 82}>{saves}</text>
				{#if node.rows.length}
					<line
						class="divider"
						x1={x + 12}
						y1={y + STRIKE.rule}
						x2={x + width - 12}
						y2={y + STRIKE.rule}
					/>
				{/if}
				{#each node.rows as [name, figures], index}
					{@const row = y + STRIKE.rule + 18 + index * STRIKE.row}
					<text x={x + 12} y={row}>{name}</text>
					<text class="mono" x={x + width - 12} y={row} text-anchor="end">{figures}</text>
				{/each}
			{:else if node.kind === 'pill'}
				<rect class="pill" {x} {y} {width} {height} rx={height / 2} />
				<text class="mono" x={x + width / 2} y={y + 17} text-anchor="middle">{node.text}</text>
			{:else if node.kind === 'result'}
				{@const result = lanes.result}
				{@const bar = width - 24}
				{@const shares = [
					['attacker', result.attacker_wins],
					['draw', result.draw],
					['target', result.target_wins]
				] as const}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<text class="title" x={x + 12} y={y + 23}>Combat result</text>
				{#each [lanes.units.attacker.name, lanes.units.target.name] as name, index}
					<text x={x + 12} y={y + 45 + index * 19}>{name}</text>
					<text class="mono" x={x + width - 12} y={y + 45 + index * 19} text-anchor="end"
						>{mean(index ? result.scores.target : result.scores.attacker)}</text
					>
				{/each}
				{#each shares as [tone, p], index}
					{@const before = shares.slice(0, index).reduce((sum, [, q]) => sum + q, 0)}
					<rect
						class="share {tone}"
						x={x + 12 + before * bar}
						y={y + 78}
						width={p * bar}
						height="12"
					/>
					<rect
						class="share {tone}"
						x={x + 12 + index * (bar / 3)}
						y={y + 102}
						width="10"
						height="10"
					/>
					<text class="mono" x={x + 26 + index * (bar / 3)} y={y + 111}>{percent(p)}</text>
				{/each}
			{:else if node.kind === 'break'}
				{@const test = lanes.breaks[node.lane]}
				<rect class="card" {x} {y} {width} {height} rx="8" />
				<rect class="spine" {x} {y} width="4" {height} />
				<text class="title" x={x + INSET} y={y + 22}>Break test</text>
				<text class="mono" x={x + INSET} y={y + 43}>Ld {test.leadership ?? '–'}</text>
				<text class="mono" x={x + width - 14} y={y + 43} text-anchor="end"
					>{signed(test.margin)}</text
				>
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
	.node.on .pill,
	.node:focus-visible .card {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.attacker .spine,
	.charge .spine,
	.attacker .model.command,
	.share.attacker {
		fill: var(--attacker);
	}
	.target .spine,
	.reaction .spine,
	.target .model.command,
	.share.target {
		fill: var(--target);
	}
	.share.draw {
		fill: var(--neutral);
	}
	.attacker .header,
	.attacker .chip,
	.attacker .fill {
		fill: var(--attacker-tint);
	}
	.target .header,
	.target .chip,
	.target .fill {
		fill: var(--target-tint);
	}
	.target .fill.worst {
		fill: color-mix(in srgb, var(--series-2) 32%, var(--plane));
	}
	.attacker .fill.worst {
		fill: color-mix(in srgb, var(--series-1) 32%, var(--plane));
	}
	.chip {
		stroke: #c9c9c9;
	}
	.chip-text {
		font-size: 11px;
		text-anchor: middle;
	}
	.model {
		stroke-width: 1;
	}
	.attacker .model {
		fill: var(--attacker-tint);
		stroke: var(--attacker);
	}
	.target .model {
		fill: var(--target-tint);
		stroke: var(--target);
	}
	.divider {
		stroke: #e3e3e3;
	}
	.pill {
		fill: var(--panel);
	}
	.attacker .pill {
		stroke: var(--attacker);
	}
	.target .pill {
		stroke: var(--target);
	}
	.field {
		fill: #fafafa;
		stroke: #9a9a9a;
	}
	.segment rect {
		fill: var(--panel);
		stroke: var(--line);
	}
	.segment text {
		font-size: 12px;
		text-anchor: middle;
	}
	.segment.on rect {
		fill: var(--target);
		stroke: var(--target);
	}
	.segment.on text {
		fill: var(--on-accent);
	}
	.segment.off rect {
		fill: #f4f4f4;
		stroke: #d6d6d6;
	}
	.segment.off text {
		fill: #b0b0b0;
	}
</style>
