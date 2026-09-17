<script lang="ts">
	import Graph from '$lib/graph/Graph.svelte';

	let { data } = $props();
</script>

{#if data.program}
	<Graph program={data.program} />
{:else}
	<p class="meta empty">No program.</p>
{/if}

<style>
	.empty {
		padding: 0 var(--space-3);
	}
</style>
