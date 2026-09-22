<script lang="ts">
	import { percent } from './scale';

	export interface Segment {
		label: string;
		value: number;
	}

	interface Props {
		segments: Segment[];
		/**
		 * `ordinal` for outcomes that get steadily worse, light to dark.
		 * `poles` for two sides about a neutral middle, which the middle segment takes.
		 */
		scheme?: 'ordinal' | 'poles';
	}

	let { segments, scheme = 'ordinal' }: Props = $props();

	const ORDINAL = ['var(--ordinal-1)', 'var(--ordinal-2)', 'var(--ordinal-3)', 'var(--ordinal-4)'];
	const POLES = ['var(--series-1)', 'var(--neutral)', 'var(--series-2)'];

	const ramp = $derived(scheme === 'poles' ? POLES : ORDINAL);
	const total = $derived(segments.reduce((sum, each) => sum + each.value, 0) || 1);

	// Only label inside a segment wide enough to hold the text; the legend
	// carries the rest, so nothing is ever clipped.
	const roomy = (value: number) => value / total > 0.16;
</script>

<div class="bar">
	{#each segments as segment, index}
		{#if segment.value > 0}
			<div
				class="cell"
				style="flex: {segment.value / total} 0 0; background: {ramp[index % ramp.length]}"
			>
				{#if roomy(segment.value)}<span>{percent(segment.value)}</span>{/if}
			</div>
		{/if}
	{/each}
</div>

<div class="legend">
	{#each segments as segment, index}
		<span>
			<i style="background: {ramp[index % ramp.length]}"></i>
			{segment.label}
			<b class="num">{percent(segment.value)}</b>
		</span>
	{/each}
</div>
