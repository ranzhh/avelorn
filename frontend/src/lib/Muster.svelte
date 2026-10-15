<script lang="ts">
	import { untrack } from 'svelte';

	import { entry } from '$lib/corpus';
	import { cost, keys } from '$lib/options';
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
		if (!Number.isInteger(size) || size < 1) return;
		pending = setTimeout(() => onsubmit(size, chosen), 300);
	}

	const held = $derived(keys(offered));

	function key(event: KeyboardEvent) {
		if (event.metaKey || event.ctrlKey || event.altKey) return;
		if (event.key === 'Enter' && event.currentTarget instanceof HTMLInputElement) {
			if (event.currentTarget.type !== 'number') return;
			event.preventDefault();
			clearTimeout(pending);
			onsubmit(size, chosen);
			return;
		}
		if (event.key.length !== 1 || /[\d ]/.test(event.key)) return;
		event.preventDefault();
		const option = offered.find((each) => held.get(each.id)?.letter === event.key.toLowerCase());
		if (!option) return;
		chosen = chosen.includes(option.id)
			? chosen.filter((id) => id !== option.id)
			: [...chosen, option.id];
		edited();
	}

	// A fresh datasheet means a fresh draft: the previous unit's options are not
	// on offer, and its size is not this one's.
	$effect(() => {
		const slug = unit;
		entry('unit', slug).then((sheet) => {
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
			<input
				class="input"
				type="number"
				min="1"
				bind:value={size}
				oninput={edited}
				onkeydown={key}
			/>
			{#if allowed}<span class="price">{allowed}</span>{/if}
		</span>
	</label>

	{#if offered.length}
		<div class="options">
			{#each offered as option}
				{@const bound = held.get(option.id)}
				<label class="check">
					<input
						type="checkbox"
						value={option.id}
						bind:group={chosen}
						onchange={edited}
						onkeydown={key}
					/>
					{#if bound && bound.at >= 0}
						<span
							>{option.name.slice(0, bound.at)}<u>{option.name[bound.at]}</u>{option.name.slice(
								bound.at + 1
							)}</span
						>
					{:else}
						<span
							>{option.name}{#if bound?.hint}<span class="price hint"
									>(<u>{bound.hint[0]}</u>{bound.hint.slice(1)})</span
								>{/if}</span
						>
					{/if}
					{#if cost(option)}<span class="price">{cost(option)}</span>{/if}
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
	.hint {
		margin-left: 0.3em;
	}
</style>
