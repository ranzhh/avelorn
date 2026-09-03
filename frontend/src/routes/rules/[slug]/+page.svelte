<script lang="ts">
	let { data } = $props();

	const rule = $derived(data.rule);
	const corrections = $derived(rule.corrections ?? []);
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

{#if rule.caveats}
	<h2>Left out</h2>
	<p class="meta">{rule.caveats}</p>
{/if}

{#if corrections.length}
	<h2>Corrected from the source</h2>
	{#each corrections as correction}
		<p class="meta">
			<code>{correction.op} {correction.path}</code>
			{correction.why}
		</p>
	{/each}
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
