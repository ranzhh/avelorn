<script lang="ts">
	import { api, type MusteredUnit, type UnitOption } from '$lib/api/client';

	const STORAGE_KEY = 'avelorn:list';

	let { data } = $props();

	let blocks = $state<MusteredUnit[]>([]);
	let slug = $state('');
	let size = $state(5);
	let chosen = $state<string[]>([]);
	let offered = $state<UnitOption[]>([]);
	let refusal = $state('');

	const total = $derived(blocks.reduce((sum, block) => sum + block.points, 0));
	const client = () => api(window.location.origin, fetch);

	// The list is the browser's, not the server's: there is no store behind the
	// API yet, so a reload would otherwise lose it.
	$effect(() => {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved) blocks = JSON.parse(saved);
	});

	$effect(() => {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(blocks));
	});

	async function pick(event: Event) {
		slug = (event.currentTarget as HTMLSelectElement).value;
		chosen = [];
		offered = [];
		refusal = '';
		if (!slug) return;
		const { data: unit } = await client().GET('/units/{slug}', { params: { path: { slug } } });
		if (!unit) return;
		offered = unit.options ?? [];
		size = unit.unit_size.min;
	}

	async function add() {
		refusal = '';
		const { data: block, error: refused } = await client().POST('/muster', {
			body: { unit: slug, size, options: chosen }
		});
		if (!block) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not muster that';
			return;
		}
		blocks = [...blocks, block];
	}

	function remove(at: number) {
		blocks = blocks.filter((_, index) => index !== at);
	}

	function cost(option: UnitOption) {
		if (option.points_budget) return `up to ${option.points_budget} pts`;
		if (!option.points) return '';
		return `${option.points} pts${option.per_model ? '/model' : ''}`;
	}
</script>

<h1>Army list</h1>
<p class="meta">
	Blocks and what they cost. Nothing here checks whether the list is legal — army composition is not
	modelled yet.
</p>

<fieldset>
	<legend>Add a block</legend>

	<label>
		Unit
		<select onchange={pick}>
			<option value="">choose a datasheet</option>
			{#each data.units as unit}
				<option value={unit.id}>{unit.name} — {unit.points} pts/model</option>
			{/each}
		</select>
	</label>

	{#if slug}
		<label>
			Models
			<input type="number" min="1" bind:value={size} />
		</label>

		{#if offered.length}
			<div class="options">
				{#each offered as option}
					<label class="option">
						<input type="checkbox" value={option.name} bind:group={chosen} />
						{option.name}
						<span class="meta">{cost(option)}</span>
						{#if offered.filter((o) => o.name === option.name).length > 1}
							<span class="warn">name repeats; both are bought together</span>
						{/if}
					</label>
				{/each}
			</div>
		{/if}

		<button onclick={add}>Add to list</button>
	{/if}

	{#if refusal}
		<p class="refusal">{refusal}</p>
	{/if}
</fieldset>

{#if blocks.length}
	<table>
		<thead>
			<tr>
				<th>Block</th>
				<th>Models</th>
				<th>Options</th>
				<th>Points</th>
				<th></th>
			</tr>
		</thead>
		<tbody>
			{#each blocks as block, at}
				<tr>
					<td>{block.name}</td>
					<td>{block.size}</td>
					<td class="meta">{block.options.join(', ') || '—'}</td>
					<td>{block.points}</td>
					<td><button class="link" onclick={() => remove(at)}>remove</button></td>
				</tr>
			{/each}
		</tbody>
		<tfoot>
			<tr>
				<th colspan="3">Total</th>
				<th>{total}</th>
				<th></th>
			</tr>
		</tfoot>
	</table>
{:else}
	<p class="meta">No blocks yet.</p>
{/if}

<style>
	fieldset {
		border: 1px solid var(--rule);
		border-radius: 3px;
		padding: 1rem;
		margin-bottom: 1.5rem;
	}

	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	select,
	input[type='number'] {
		font: inherit;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
	}

	.options {
		margin: 0.6rem 0;
	}

	.option {
		font-size: 0.9rem;
		margin-bottom: 0.2rem;
	}

	button {
		font: inherit;
		padding: 0.35rem 0.8rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
		cursor: pointer;
	}

	button.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--muted);
		text-decoration: underline;
	}

	.meta {
		color: var(--muted);
		font-size: 0.85rem;
	}

	.warn {
		color: #8a5a00;
		font-size: 0.8rem;
	}

	.refusal {
		color: #8a1c1c;
		font-size: 0.9rem;
	}

	tfoot th {
		border-top: 1px solid var(--ink);
	}
</style>
