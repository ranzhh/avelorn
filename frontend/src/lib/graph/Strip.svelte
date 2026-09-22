<script lang="ts">
	import { exact, labelEvery } from '$lib/charts/scale';
	import type { Distribution } from './types';

	interface Props {
		distribution: Distribution;
		width?: number;
	}

	let { distribution, width = 104 }: Props = $props();

	const HEIGHT = 28;

	let shown = $state<number | null>(null);

	const outcomes = $derived(distribution.outcomes);
	const peak = $derived(Math.max(...outcomes.map((outcome) => outcome.p), 1e-9));
	const every = $derived(labelEvery(outcomes.length, width));
</script>

<div class="strip" style="width: {width}px">
	<div class="bars" style="height: {HEIGHT}px">
		{#each outcomes as outcome, index}
			<button
				class="bar"
				class:lit={shown === index}
				aria-label="{distribution.label} {outcome.value}: {exact(outcome.p)}"
				onpointerenter={() => (shown = index)}
				onpointerleave={() => (shown = null)}
				onfocus={() => (shown = index)}
				onblur={() => (shown = null)}
			>
				<i style="height: {Math.max((outcome.p / peak) * HEIGHT, outcome.p > 0 ? 1 : 0)}px"></i>
			</button>
		{/each}
	</div>
	<div class="values">
		{#each outcomes as outcome, index}
			<span>{index % every === 0 ? outcome.value : ''}</span>
		{/each}
	</div>
	{#if shown !== null}
		<div class="tip" style="left: {((shown + 0.5) / outcomes.length) * 100}%">
			{outcomes[shown].value} · {exact(outcomes[shown].p)}
		</div>
	{/if}
</div>

<style>
	.strip {
		position: relative;
	}

	.bars,
	.values {
		display: flex;
		align-items: flex-end;
		gap: 1px;
	}

	.bar {
		flex: 1 1 0;
		min-width: 0;
		height: 100%;
		display: flex;
		align-items: flex-end;
		padding: 0;
		background: none;
		border: none;
		cursor: default;
	}

	.bar i {
		display: block;
		width: 100%;
		background: var(--series-1);
		border-radius: 1px 1px 0 0;
	}

	.bar.lit i {
		background: var(--accent-ink);
	}

	.values {
		border-top: 1px solid var(--faint);
		padding-top: 1px;
	}

	.values span {
		flex: 1 1 0;
		min-width: 0;
		overflow: hidden;
		text-align: center;
		font: 9px var(--font-mono);
		color: var(--dim);
	}

	.tip {
		position: absolute;
		bottom: calc(100% + 2px);
		transform: translateX(-50%);
		padding: 1px var(--space-2);
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--ink);
		background: var(--panel);
		border: 1px solid var(--faint);
		border-radius: var(--radius-sm);
		white-space: nowrap;
		pointer-events: none;
		z-index: 1;
	}
</style>
