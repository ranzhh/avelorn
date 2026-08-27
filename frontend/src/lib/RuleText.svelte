<script lang="ts">
	import type { Rule } from '$lib/api/client';

	let { rule }: { rule: Rule } = $props();

	const where = $derived(
		[rule.category, rule.page && `page ${rule.page}`].filter(Boolean).join(' · ')
	);
</script>

{#if where}<p class="meta">{where}</p>{/if}

{#each rule.paragraphs as paragraph}
	<p class="text">{paragraph}</p>
{/each}

<p class="reach">
	{#if rule.effects?.length}
		<span class="pos">reaches the maths</span>
		· {rule.effects.length}
		{rule.effects.length === 1 ? 'effect' : 'effects'}
	{:else}
		<span class="dim">printed only, no effect the engine applies</span>
	{/if}
</p>

{#if rule.notes}
	<h4>left out</h4>
	<p class="meta">{rule.notes}</p>
{/if}

<style>
	h4 {
		margin: var(--space-3) 0 var(--space-1);
		font: 600 var(--text-xs) / 1 var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--dim);
	}

	.meta {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	.text {
		margin-top: var(--space-2);
		font-size: var(--text-sm);
	}

	.reach {
		margin-top: var(--space-3);
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}

	.dim {
		color: var(--faint);
	}
</style>
