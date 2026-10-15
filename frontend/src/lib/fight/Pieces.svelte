<script lang="ts">
	import { percent } from '$lib/charts/scale';
	import { pieces, type Box, type Layer, type Tone } from './faces';

	interface Props {
		box: Box;
		least: number;
		layers: Layer[];
		/** What a count counts, for its tooltip. */
		unit: string;
	}

	let { box, least, layers, unit }: Props = $props();

	const colours: Record<Tone, string> = {
		attacker: 'var(--attacker, var(--series-1))',
		target: 'var(--target, var(--series-2))',
		draw: 'var(--neutral)',
		short: 'var(--short, #cbcbcb)'
	};
</script>

{#each pieces(least, layers) as piece}
	{@const at = box.x + piece.from * box.width}
	{@const wide = piece.p * box.width}
	<rect
		class="piece"
		x={at}
		y={box.y}
		width={wide}
		height={box.height}
		fill={colours[piece.tone]}
		fill-opacity={piece.shade}
	>
		<title
			>{piece.tone === 'short'
				? `falls short: ${percent(piece.p)}`
				: `${piece.count} ${unit}: ${percent(piece.p)}`}</title
		>
	</rect>
	{@const label =
		piece.tone === 'short'
			? wide >= 64
				? `short ${percent(piece.p)}`
				: wide >= 34
					? 'short'
					: ''
			: wide >= 11
				? String(piece.count)
				: ''}
	{#if label}
		<text
			class="piece-text"
			class:light={piece.tone !== 'short' && piece.shade > 0.55}
			x={at + wide / 2}
			y={box.y + box.height - 3}
			text-anchor="middle">{label}</text
		>
	{/if}
{/each}

<style>
	.piece-text {
		font-size: 11px;
		pointer-events: none;
	}
	.piece-text.light {
		fill: #fff;
	}
</style>
