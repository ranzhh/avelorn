<script lang="ts">
	import type { Rule } from '$lib/api/client';

	let { rule }: { rule: Rule } = $props();

	const where = $derived(
		[rule.category, rule.page && `page ${rule.page}`].filter(Boolean).join(' · ')
	);
</script>

<p class="meta where">
	<span>{where}</span>
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

{#each rule.paragraphs as paragraph}
	<p class="text">{paragraph}</p>
{/each}

{#if rule.notes}
	<h4>left out</h4>
	<p class="meta">{rule.notes}</p>
{/if}
