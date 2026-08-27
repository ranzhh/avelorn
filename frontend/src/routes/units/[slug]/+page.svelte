<script lang="ts">
	import { resolve } from '$app/paths';

	let { data } = $props();

	// Printed order, not the order a profile happens to be written in.
	const CHARACTERISTICS = ['M', 'WS', 'BS', 'S', 'T', 'W', 'I', 'A', 'Ld'] as const;

	const unit = $derived(data.unit);
	const size = $derived(
		unit.unit_size.max ? `${unit.unit_size.min}–${unit.unit_size.max}` : `${unit.unit_size.min}+`
	);
</script>

<h1>{unit.name}</h1>
<p class="meta">{unit.troop_type} · {size} models · {unit.points} points per model</p>

<table>
	<thead>
		<tr>
			<th>Profile</th>
			{#each CHARACTERISTICS as key (key)}
				<th>{key}</th>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#each unit.profiles as profile}
			<tr>
				<td>{profile.name}</td>
				{#each CHARACTERISTICS as key (key)}
					<td>{profile.characteristics?.[key] ?? '–'}</td>
				{/each}
			</tr>
		{/each}
	</tbody>
</table>

{#if unit.equipment?.length}
	<h2>Equipment</h2>
	<ul>
		{#each unit.equipment as item}
			<li>{item}</li>
		{/each}
	</ul>
{/if}

{#if unit.special_rules?.length}
	<h2>Special rules</h2>
	<ul>
		{#each unit.special_rules as rule}
			<li>
				{#if rule.slug}
					<a href={resolve('/rules/[slug]', { slug: rule.slug })}>{rule.name}</a>
				{:else}
					<span class="unmodelled">{rule.name}</span>
					<span class="meta">not modelled</span>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

{#if unit.options?.length}
	<h2>Options</h2>
	<ul>
		{#each unit.options as option}
			<li>
				{option.name}
				<span class="meta">
					{#if option.points_budget}up to {option.points_budget} pts
					{:else if option.points}{option.points} pts{#if option.per_model}
							per model{/if}
					{/if}
				</span>
			</li>
		{/each}
	</ul>
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

	.unmodelled {
		color: var(--dim);
		text-decoration: underline dotted var(--line);
	}
</style>
