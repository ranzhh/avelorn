<script lang="ts">
	import { entry } from '$lib/corpus';
	import type { Reference } from '$lib/api/client';

	interface Props {
		of: Reference[];
		/** Follow one, opening whatever kind it turns out to name. */
		onopen: (reference: Reference) => void;
	}

	let { of, onopen }: Props = $props();
</script>

<div class="cluster tight">
	{#each of as reference (reference.name)}
		{#if reference.slug && reference.kind}
			{@const kind = reference.kind}
			{@const slug = reference.slug}
			<!-- Warmed on hover, so the pane a click opens has its body to hand. -->
			<button
				class="pill link"
				onpointerenter={() => entry(kind, slug)}
				onclick={() => onopen(reference)}
			>
				{reference.name}
			</button>
		{:else}
			<span class="pill dead" title="the corpus prints this name and holds no entry">
				{reference.name}
			</span>
		{/if}
	{/each}
</div>

<style>
	.tight {
		gap: var(--space-1);
	}

	.link {
		color: var(--accent-ink);
		cursor: pointer;
		font-family: var(--font-mono);
	}

	.link:hover {
		border-color: var(--accent);
	}

	/* Nothing to open: the name is printed and no entry stands behind it. */
	.dead {
		color: var(--faint);
		border-style: dashed;
	}
</style>
