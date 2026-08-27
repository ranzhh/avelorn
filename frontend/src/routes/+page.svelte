<script lang="ts">
	import { resolve } from '$app/paths';

	import { listing, reorder, sizeRange, type Column, type Order } from '$lib/listing';

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
				<td class="num">{unit.points}</td>
				<td class="num">{sizeRange(unit)}</td>
				<td class="dim">{unit.troop_type}</td>
				<td class="armies">
					{#each unit.armies as army, index}{index ? ', ' : ''}{army}{/each}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	.head {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3) var(--space-3);
	}

	.head .input {
		width: 16rem;
	}

	th button {
		font: inherit;
		color: inherit;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-transform: inherit;
		letter-spacing: inherit;
	}

	th button:hover {
		color: var(--ink);
	}

	th.on button {
		color: var(--accent-ink);
	}

	th.num button {
		float: right;
	}

	.caret {
		margin-left: 2px;
	}

	td.dim {
		color: var(--dim);
	}

	td.armies {
		color: var(--dim);
		font-size: var(--text-sm);
	}
</style>
