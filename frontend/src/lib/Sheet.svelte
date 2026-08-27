<script lang="ts">
	import Chips from '$lib/Chips.svelte';
	import { cost } from '$lib/options';
	import type { Reference, Unit } from '$lib/api/client';

	interface Props {
		unit: Unit;
		/** Follow a printed name to its entry, opening a pane on top of this one. */
		onopen: (reference: Reference) => void;
	}

	let { unit, onopen }: Props = $props();

	// Printed order, not the order a profile happens to be written in.
	const CHARACTERISTICS = ['M', 'WS', 'BS', 'S', 'T', 'W', 'I', 'A', 'Ld'] as const;

	const size = $derived(
		unit.unit_size.max ? `${unit.unit_size.min}–${unit.unit_size.max}` : `${unit.unit_size.min}+`
	);
</script>

<p class="meta">{unit.troop_type} · {size} models · {unit.points} pts/model</p>

<table>
	<thead>
		<tr>
			<th></th>
			{#each CHARACTERISTICS as key (key)}
				<th class="num">{key}</th>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#each unit.profiles as profile}
			<tr>
				<td class="who">
					{profile.name}
					{#if profile.role !== 'rank-and-file'}<span class="role">{profile.role}</span>{/if}
				</td>
				{#each CHARACTERISTICS as key (key)}
					<td class="num">{profile.characteristics?.[key] ?? '–'}</td>
				{/each}
			</tr>
		{/each}
	</tbody>
</table>

{#if unit.equipment?.length}
	<h4>equipment</h4>
	<Chips of={unit.equipment} {onopen} />
{/if}

{#if unit.special_rules?.length}
	<h4>special rules</h4>
	<Chips of={unit.special_rules} {onopen} />
{/if}

{#if unit.options?.length}
	<h4>options</h4>
	<table>
		<tbody>
			{#each unit.options as option}
				<tr>
					<td class="who">{option.name}</td>
					<td class="num">{cost(option)}</td>
				</tr>
			{/each}
		</tbody>
	</table>
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

	table {
		margin-top: var(--space-2);
	}

	th,
	td {
		padding: 1px var(--space-1);
	}

	.who {
		width: 99%;
		color: var(--ink);
	}

	.role {
		margin-left: var(--space-1);
		font-size: var(--text-xs);
		color: var(--faint);
	}
</style>
