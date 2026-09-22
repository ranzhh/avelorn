<script lang="ts">
	import { resolve } from '$app/paths';

	import { fielded, listing, reorder, sizeRange, type Column, type Order } from '$lib/listing';

	let { data } = $props();

	let needle = $state('');
	let order = $state<Order>({ column: 'name', descending: false });

	const rows = $derived(listing(data.units, needle, order));

	const COLUMNS: { key: Column; label: string; numeric?: boolean }[] = [
		{ key: 'name', label: 'unit' },
		{ key: 'points', label: 'pts', numeric: true },
		{ key: 'size', label: 'size', numeric: true },
		{ key: 'troop_type', label: 'troop type' },
		{ key: 'armies', label: 'army' }
	];
</script>

<div class="head">
	<input class="input" bind:value={needle} placeholder="filter" />
	<span class="meta num">{rows.length}/{data.units.length}</span>
</div>

<table>
	<thead>
		<tr>
			{#each COLUMNS as column}
				<th class:num={column.numeric} class:on={order.column === column.key}>
					<button onclick={() => (order = reorder(order, column.key))}>
						{column.label}{#if order.column === column.key}<span class="caret"
								>{order.descending ? '▾' : '▴'}</span
							>{/if}
					</button>
				</th>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#each rows as unit (unit.id)}
			<tr>
				<td><a href={resolve('/units/[slug]', { slug: unit.id })}>{unit.name}</a></td>
				<td class="num">{fielded(unit)}</td>
				<td class="num">{sizeRange(unit.unit_size)}</td>
				<td class="dim">{unit.troop_type}</td>
				<td class="armies">
					{#each unit.armies as army, index}{index ? ', ' : ''}{army}{/each}
				</td>
			</tr>
		{/each}
	</tbody>
</table>
