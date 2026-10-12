<script lang="ts">
	import Panes from '$lib/Panes.svelte';
	import Sheet from '$lib/Sheet.svelte';
	import type { Reference } from '$lib/api/client';

	let { data } = $props();

	let panes = $state<Panes | null>(null);

	function open(reference: Reference) {
		if (!reference.kind || !reference.slug) return;
		panes?.show({ subject: reference.kind, slug: reference.slug, title: reference.name });
	}
</script>

<article class="page">
	<h1>{data.unit.name}</h1>
	<Sheet unit={data.unit} onopen={open} />
</article>

<Panes bind:this={panes} />
