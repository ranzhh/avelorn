<script lang="ts">
	import Warn from '$lib/Warn.svelte';
	import type { Rule } from '$lib/api/client';

	let { rule }: { rule: Rule } = $props();

	const where = $derived(
		[rule.category, rule.page && `page ${rule.page}`].filter(Boolean).join(' · ')
	);
</script>

<p class="meta where">
	<span>{where}</span>
	<Warn notes={rule.notes ? [rule.notes] : []} />
	{#if rule.effects?.length}
		<span class="status on" role="img" aria-label="implemented in the engine">
			✓<span class="says"><b>Implemented</b> in the engine</span>
		</span>
	{:else}
		<span class="status" role="img" aria-label="not implemented in the engine">
			<span class="says"><b>Not implemented</b> in the engine</span>
		</span>
	{/if}
</p>

{#if rule.flavour}
	<p class="text flavour">{rule.flavour}</p>
{/if}

{#each rule.paragraphs as paragraph}
	<p class="text">{paragraph}</p>
{/each}
