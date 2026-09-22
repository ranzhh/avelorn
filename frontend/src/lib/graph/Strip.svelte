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
		align-items: end;
		gap: 1px;
	}
	.bar {
		flex: 1;
		height: 100%;
		padding: 0;
		border: 0;
		background: none;
	}
	.bar i {
		display: block;
		width: 100%;
		background: #333;
	}
	.values {
		border-top: 1px solid #777;
		font-size: 0.65rem;
	}
	.values span {
		flex: 1;
		text-align: center;
	}
	.tip {
		position: absolute;
		bottom: 100%;
		padding: 0.15rem;
		border: 1px solid #777;
		background: #fff;
		font-size: 0.7rem;
	}
</style>
