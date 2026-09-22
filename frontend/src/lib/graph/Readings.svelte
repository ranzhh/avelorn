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
		display: grid;
		gap: 0.15rem;
	}
	.label {
		font-size: 0.75rem;
		color: #555;
	}
</style>
