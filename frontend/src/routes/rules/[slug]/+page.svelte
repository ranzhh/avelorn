<script lang="ts">
	let { data } = $props();

	const rule = $derived(data.rule);
</script>

<h1>{rule.name}</h1>
{#if rule.category || rule.page}
	<p class="meta">
		{[rule.category, rule.page && `page ${rule.page}`].filter(Boolean).join(' · ')}
	</p>
{/if}

{#if rule.flavour}
	<p class="flavour">{rule.flavour}</p>
{/if}

{#each rule.paragraphs as paragraph}
	<p>{paragraph}</p>
{/each}

{#if rule.notes}
	<h2>Left out</h2>
	<p class="meta">{rule.notes}</p>
{/if}

<style>
	h1 {
		margin-bottom: 0.2rem;
	}

	h2 {
		font-size: 1rem;
		margin-top: 1.5rem;
	}

	.meta {
		color: var(--dim);
		font-size: 0.85rem;
	}

	.flavour {
		font-style: italic;
		color: var(--dim);
	}
</style>
