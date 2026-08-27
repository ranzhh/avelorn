<script lang="ts">
	import { untrack } from 'svelte';

	import { datasheet } from '$lib/datasheets';
	import { cost, repeated } from '$lib/options';
	import { sizeRange } from '$lib/listing';
	import type { UnitOption } from '$lib/api/client';

	interface Props {
		unit: string;
		size: number;
		options: string[];
		/** Unused when `live`, which has no button to label. */
		submitLabel?: string;
		refusal?: string;
		onsubmit: (size: number, options: string[]) => void;
		oncancel?: () => void;
		/** Apply each edit as it is made, with no buttons to press. */
		live?: boolean;
	}

	let {
		unit,
		size: initialSize,
		options: initialOptions,
		submitLabel = '',
		refusal = '',
		onsubmit,
		oncancel,
		live = false
	}: Props = $props();

	// Seeded from the block once, then owned here: this is a draft, and the
	// caller remounts the editor when it should be seeded from something else.
	let size = $state(untrack(() => initialSize));
	let chosen = $state(untrack(() => [...initialOptions]));
	let offered = $state<UnitOption[]>([]);
	let allowed = $state('');

	// Typing 20 passes through 2, so a live edit waits for the keystrokes to
	// stop before costing anything.
	let pending: ReturnType<typeof setTimeout> | undefined;
	function edited() {
		if (!live) return;
		clearTimeout(pending);
		pending = setTimeout(() => onsubmit(size, chosen), 300);
	}

	// A fresh datasheet means a fresh draft: the previous unit's options are not
	// on offer, and its size is not this one's.
	$effect(() => {
		const slug = unit;
		datasheet(slug).then((sheet) => {
			if (!sheet || slug !== unit) return;
			offered = sheet.options ?? [];
			allowed = sizeRange(sheet.unit_size);
		});
	});
</script>

<div class="muster">
	<label class="field">
		<span>models</span>
		<span class="cluster tight">
			<input class="input" type="number" min="1" bind:value={size} oninput={edited} />
			{#if allowed}<span class="pill">{allowed}</span>{/if}
		</span>
	</label>

	{#if offered.length}
		<div class="options">
			{#each offered as option}
				<label class="check">
					<input type="checkbox" value={option.name} bind:group={chosen} onchange={edited} />
					<span>{option.name}</span>
					{#if cost(option)}<span class="pill">{cost(option)}</span>{/if}
					{#if repeated(offered, option.name)}<span class="warn">×2</span>{/if}
				</label>
			{/each}
		</div>
	{/if}

	{#if refusal}
		<p class="refuse">{refusal}</p>
	{/if}

	{#if !live}
		<div class="cluster actions">
			<button class="btn btn-primary btn-sm" onclick={() => onsubmit(size, chosen)}>
				{submitLabel}
			</button>
			{#if oncancel}
				<button class="btn btn-ghost btn-sm" onclick={oncancel}>cancel</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.options {
		margin: var(--space-2) 0;
	}

	.actions {
		gap: var(--space-2);
		margin-top: var(--space-2);
	}

	.tight {
		gap: var(--space-2);
	}

	.warn {
		font: var(--text-xs) / 1.7 var(--font-mono);
		color: var(--ordinal-1);
	}
</style>
