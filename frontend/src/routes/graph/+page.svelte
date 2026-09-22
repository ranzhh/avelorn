<script lang="ts">
	import Graph from '$lib/graph/Graph.svelte';

	let { data } = $props();
</script>

{#if data.program}
	<Graph program={data.program} />
{:else}
	<p class="meta empty">No program.</p>
{/if}
