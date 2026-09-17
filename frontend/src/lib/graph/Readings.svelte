<script lang="ts">
	import Strip from './Strip.svelte';
	import type { Reading } from './types';

	interface Props {
		readings: Reading[];
		width?: number;
	}

	let { readings, width = 104 }: Props = $props();
</script>

{#each readings as reading}
	<div class="reading">
		{#if 'outcomes' in reading}
			<span class="label">{reading.label}</span>
			<Strip distribution={reading} {width} />
		{:else}
			<span class="label">{reading.label}</span>
			<b class="num">{reading.value}</b>
		{/if}
	</div>
{/each}

<style>
	.reading {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.label {
		font-size: var(--text-xs);
		color: var(--dim);
		white-space: nowrap;
	}

	b {
		font-weight: 400;
		font-size: var(--text-sm);
		color: var(--ink);
	}
</style>
