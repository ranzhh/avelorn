<script lang="ts">
	import { resolve } from '$app/paths';

	let { data } = $props();

	let query = $state('');

	const matches = $derived(
		data.units.filter((unit) => unit.name.toLowerCase().includes(query.trim().toLowerCase()))
	);

	const size = (unit: (typeof data.units)[number]) =>
		unit.unit_size.max ? `${unit.unit_size.min}–${unit.unit_size.max}` : `${unit.unit_size.min}+`;
</script>

<label>
	Filter
	<input bind:value={query} placeholder="name" />
</label>

<p>{matches.length} of {data.units.length} datasheets</p>

<table>
	<thead>
		<tr>
			<th>Unit</th>
			<th>Troop type</th>
			<th>Size</th>
			<th>Points</th>
		</tr>
	</thead>
	<tbody>
		{#each matches as unit (unit.id)}
			<tr>
				<td><a href={resolve('/units/[slug]', { slug: unit.id })}>{unit.name}</a></td>
				<td>{unit.troop_type}</td>
				<td>{size(unit)}</td>
				<td>{unit.points}</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	label {
		display: block;
		margin-bottom: 0.5rem;
	}

	input {
		font: inherit;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
	}

	p {
		color: var(--muted);
		font-size: 0.85rem;
	}
</style>
