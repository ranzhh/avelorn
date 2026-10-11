<script lang="ts">
	import { percent } from '$lib/charts/scale';
	import { MARK, STRIKE, type Box, type Face, type Lane } from './faces';

	interface Props {
		face: Face;
		box: Box;
		/** The side whose colour the card wears, if any. */
		tone: Lane | null;
		open: boolean;
	}

	let { face, box, tone, open }: Props = $props();

	const classes = { title: 'title', text: '', small: 'small', mono: 'mono', chip: 'small' };
</script>

<g class="face {tone ?? ''}" class:open transform="translate({box.x},{box.y})">
	{#if face.chrome === 'pill'}
		<rect class="pill" width={box.width} height={box.height} rx={box.height / 2} />
	{:else}
		<rect class="card" width={box.width} height={box.height} rx="8" />
	{/if}
	{#if face.chrome === 'spine'}
		<rect class="spine" width="4" height={box.height} />
	{:else if face.chrome === 'header'}
		<path
			class="header"
			d="M0,8 a8,8 0 0 1 8,-8 h{box.width - 16} a8,8 0 0 1 8,8 v{STRIKE.header - 8} h{-box.width} z"
		/>
	{/if}

	{#each face.marks as mark}
		{#if mark.kind === 'text'}
			<text class={classes[mark.font]} x={mark.x} y={mark.y} text-anchor={mark.anchor}
				>{mark.text}</text
			>
		{:else if mark.kind === 'chip'}
			{@const { x, y, width, height } = mark.box}
			<rect class="chip" class:held={mark.held} {x} {y} {width} {height} rx="10" />
			<text class="chip-text" class:held={mark.held} x={x + width / 2} y={y + 14}>{mark.text}</text>
		{:else if mark.kind === 'model'}
			{@const { x, y, width, height } = mark.box}
			<rect class="model" class:command={mark.command} {x} {y} {width} {height}>
				{#if mark.command}<title>{mark.command.name}</title>{/if}
			</rect>
			{#if mark.command}
				<text
					class="letter"
					x={x + width / 2}
					y={y + height / 2}
					font-size={Math.min(10, width - 3)}>{MARK[mark.command.kind]}</text
				>
			{/if}
		{:else if mark.kind === 'divider'}
			<line class="divider" x1="12" y1={mark.y} x2={box.width - 12} y2={mark.y} />
		{:else if mark.kind === 'shares'}
			{@const { x, y, width, height } = mark.box}
			{#each mark.shares as [share, p], index}
				{@const before = mark.shares.slice(0, index).reduce((sum, [, q]) => sum + q, 0)}
				<rect class="share {share}" x={x + before * width} {y} width={p * width} {height} />
				<rect class="share {share}" x={x + index * (width / 3)} y={y + 24} width="10" height="10" />
				<text class="mono" x={x + 14 + index * (width / 3)} y={y + 33}>{percent(p)}</text>
			{/each}
		{:else if mark.kind === 'rule'}
			<rect
				class="box"
				class:applied={mark.rule.applied}
				x={mark.x}
				y={mark.y - 10}
				width="11"
				height="11"
				rx="2"
			/>
			{#if mark.rule.applied}
				<path class="tick" d="M{mark.x + 2.5},{mark.y - 4.5} l2.5,2.5 l3.8,-5" />
			{/if}
			<text x={mark.x + 18} y={mark.y}>{mark.rule.name}</text>
			<rect
				class="who {mark.rule.side}"
				x={box.width - mark.x - 8}
				y={mark.y - 9}
				width="8"
				height="8"
			/>
		{/if}
	{/each}
</g>

<style>
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
	.title {
		font-weight: 600;
	}
	.card {
		fill: var(--panel);
		stroke: #bdbdbd;
	}
	.pill {
		fill: var(--panel);
	}
	.open .card,
	.open .pill {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.attacker .spine,
	.attacker .model.command,
	.share.attacker,
	.who.attacker {
		fill: var(--attacker);
	}
	.target .spine,
	.target .model.command,
	.share.target,
	.who.target {
		fill: var(--target);
	}
	.share.draw {
		fill: var(--neutral);
	}
	.attacker .header,
	.attacker .chip.held {
		fill: var(--attacker-tint);
	}
	.target .header,
	.target .chip.held {
		fill: var(--target-tint);
	}
	.chip {
		fill: var(--sunken);
		stroke: #d4d4d4;
	}
	.attacker .chip.held {
		stroke: var(--attacker);
	}
	.target .chip.held {
		stroke: var(--target);
	}
	.chip-text {
		font-size: 11px;
		text-anchor: middle;
		fill: var(--dim);
	}
	.chip-text.held {
		fill: var(--ink);
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
	.letter {
		fill: var(--on-accent);
		font-weight: 600;
		text-anchor: middle;
		dominant-baseline: central;
		pointer-events: none;
	}
	.divider {
		stroke: #e3e3e3;
	}
	.box {
		fill: #fff;
		stroke: #c4c4c4;
	}
	.box.applied {
		fill: #a9a9a9;
		stroke: #a9a9a9;
	}
	.tick {
		fill: none;
		stroke: #fff;
		stroke-width: 1.6;
	}
	.attacker .pill {
		stroke: var(--attacker);
	}
	.target .pill {
		stroke: var(--target);
	}
</style>
