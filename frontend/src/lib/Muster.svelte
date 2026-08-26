<script lang="ts">
	import { untrack } from 'svelte';

	import { datasheet } from '$lib/datasheets';
	import { cost, repeated } from '$lib/options';
	import type { UnitOption } from '$lib/api/client';

	interface Props {
		unit: string;
		size: number;
		options: string[];
		submitLabel: string;
		refusal?: string;
		onsubmit: (size: number, options: string[]) => void;
		oncancel?: () => void;
	}

	let {
		unit,
		size: initialSize,
		options: initialOptions,
		submitLabel,
		refusal = '',
		onsubmit,
		oncancel
	}: Props = $props();

	// Seeded from the block once, then owned here: this is a draft, and the
	// caller remounts the editor when it should be seeded from something else.
	let size = $state(untrack(() => initialSize));
	let chosen = $state(untrack(() => [...initialOptions]));
	let offered = $state<UnitOption[]>([]);
	let allowed = $state('');

	// A fresh datasheet means a fresh draft: the previous unit's options are not
	// on offer, and its size is not this one's.
	$effect(() => {
		const slug = unit;
		datasheet(slug).then((sheet) => {
			if (!sheet || slug !== unit) return;
			offered = sheet.options ?? [];
			allowed = sheet.unit_size.max
				? `${sheet.unit_size.min}–${sheet.unit_size.max}`
				: `${sheet.unit_size.min} or more`;
		});
	});
</script>

<div class="muster">
	<label>
		Models
		<input type="number" min="1" bind:value={size} />
		{#if allowed}<span class="meta">{allowed} allowed</span>{/if}
	</label>

	{#if offered.length}
		<div class="options">
			{#each offered as option}
				<label class="option">
					<input type="checkbox" value={option.name} bind:group={chosen} />
					{option.name}
					<span class="meta">{cost(option)}</span>
					{#if repeated(offered, option.name)}
						<span class="warn">name repeats; both are bought together</span>
					{/if}
				</label>
			{/each}
		</div>
	{/if}

	{#if refusal}
		<p class="refusal">{refusal}</p>
	{/if}

	<div class="actions">
		<button onclick={() => onsubmit(size, chosen)}>{submitLabel}</button>
		{#if oncancel}
			<button class="link" onclick={oncancel}>cancel</button>
		{/if}
	</div>
</div>

<style>
	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	input[type='number'] {
		font: inherit;
		width: 5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--line);
		border-radius: 3px;
		background: var(--sunken);
	}

	.options {
		margin: 0.6rem 0;
	}

	.option {
		font-size: 0.9rem;
		margin-bottom: 0.2rem;
	}

	.actions {
		display: flex;
		gap: 0.75rem;
		align-items: center;
	}

	button {
		font: inherit;
		padding: 0.35rem 0.8rem;
		border: 1px solid var(--line);
		border-radius: 3px;
		background: var(--sunken);
		cursor: pointer;
	}

	button.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--dim);
		text-decoration: underline;
	}

	.meta {
		color: var(--dim);
		font-size: 0.85rem;
	}

	.warn {
		color: var(--ordinal-1);
		font-size: 0.8rem;
	}

	.refusal {
		color: var(--neg);
		font-size: 0.9rem;
	}
</style>
