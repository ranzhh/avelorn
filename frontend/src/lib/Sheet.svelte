<script lang="ts">
	import Chips from '$lib/Chips.svelte';
	import { cost } from '$lib/options';
	import type { Reference, Unit } from '$lib/api/client';

	interface Props {
		unit: Unit;
		/** Print what the options cost. Off where the pane carries them editable. */
		pricing?: boolean;
		/** Follow a printed name to its entry, opening a pane on top of this one. */
		onopen: (reference: Reference) => void;
	}

	let { unit, pricing = true, onopen }: Props = $props();

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

{#if pricing && unit.options?.length}
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
