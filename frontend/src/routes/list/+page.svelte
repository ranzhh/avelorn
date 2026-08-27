<script lang="ts">
	import { resolve } from '$app/paths';

	import Muster from '$lib/Muster.svelte';
	import { entry } from '$lib/corpus';
	import { api, type MusteredUnit } from '$lib/api/client';

	const STORAGE_KEY = 'avelorn:list';

	let { data } = $props();

	let blocks = $state<MusteredUnit[]>([]);
	let adding = $state('');
	let addingSize = $state(1);
	let editing = $state<number | null>(null);
	let refusal = $state('');

	const total = $derived(blocks.reduce((sum, block) => sum + block.points, 0));
	const models = $derived(blocks.reduce((sum, block) => sum + block.size, 0));
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

	async function muster(unit: string, size: number, options: string[]) {
		const { data: block, error: refused } = await client().POST('/muster', {
			body: { unit, size, options }
		});
		if (block) return block;
		refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not muster that';
		return null;
	}

	async function pick(event: Event) {
		const slug = (event.currentTarget as HTMLSelectElement).value;
		refusal = '';
		editing = null;
		if (!slug) {
			adding = '';
			return;
		}
		// The size is settled before the editor exists to read it: mounting first
		// would seed the draft from the previous datasheet's minimum.
		const sheet = await entry('unit', slug);
		addingSize = sheet?.unit_size.min ?? 1;
		adding = slug;
	}

	async function add(size: number, options: string[]) {
		refusal = '';
		const block = await muster(adding, size, options);
		if (!block) return;
		blocks = [...blocks, block];
		adding = '';
	}

	async function save(at: number, size: number, options: string[]) {
		refusal = '';
		const block = await muster(blocks[at].unit, size, options);
		if (!block) return;
		blocks = blocks.map((old, index) => (index === at ? block : old));
		editing = null;
	}

	function duplicate(at: number) {
		// Already costed and already validated, so it needs no round trip.
		const copy = structuredClone($state.snapshot(blocks[at]));
		blocks = [...blocks.slice(0, at + 1), copy, ...blocks.slice(at + 1)];
		if (editing !== null && editing > at) editing += 1;
	}

	function edit(at: number) {
		refusal = '';
		adding = '';
		editing = editing === at ? null : at;
	}

	function remove(at: number) {
		// An open editor is addressed by index, so dropping a row above it has to
		// move it down or it would start editing its neighbour.
		if (editing === at) editing = null;
		else if (editing !== null && editing > at) editing -= 1;
		blocks = blocks.filter((_, index) => index !== at);
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
		<select value={adding} onchange={pick}>
			<option value="">choose a datasheet</option>
			{#each data.units as unit}
				<option value={unit.id}>{unit.name} — {unit.points} pts/model</option>
			{/each}
		</select>
	</label>

	{#if adding}
		{#key adding}
			<Muster
				unit={adding}
				size={addingSize}
				options={[]}
				submitLabel="Add to list"
				refusal={editing === null ? refusal : ''}
				onsubmit={add}
				oncancel={() => (adding = '')}
			/>
		{/key}
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
				<tr class:editing={editing === at}>
					<td>{block.name}</td>
					<td>{block.size}</td>
					<td class="meta">{block.options.join(', ') || '—'}</td>
					<td>{block.points}</td>
					<td class="row-actions">
						<button class="link" onclick={() => edit(at)}>
							{editing === at ? 'close' : 'edit'}
						</button>
						<button class="link" onclick={() => duplicate(at)}>duplicate</button>
						<button class="link" onclick={() => remove(at)}>remove</button>
					</td>
				</tr>
				{#if editing === at}
					<tr class="editor">
						<td colspan="5">
							{#key at}
								<Muster
									unit={block.unit}
									size={block.size}
									options={block.options}
									submitLabel="Save"
									{refusal}
									onsubmit={(size, options) => save(at, size, options)}
									oncancel={() => (editing = null)}
								/>
							{/key}

							<dl class="loadout">
								<dt>Carries</dt>
								<dd>{block.equipment.join(', ') || '—'}</dd>
								<dt>Rules</dt>
								<dd>
									{#each block.special_rules as rule, index}
										{#if index}<span aria-hidden="true">, </span>{/if}
										{#if rule.slug}
											<a href={resolve('/rules/[slug]', { slug: rule.slug })}>{rule.name}</a>
										{:else}
											<span class="unmodelled" title="not modelled by the engine">{rule.name}</span>
										{/if}
									{/each}
								</dd>
							</dl>
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
		<tfoot>
			<tr>
				<th>Total</th>
				<th>{models}</th>
				<th></th>
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
		border: 1px solid var(--line);
		border-radius: 3px;
		padding: 1rem;
		margin-bottom: 1.5rem;
	}

	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	select {
		font: inherit;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--line);
		border-radius: 3px;
		background: var(--sunken);
	}

	tr.editing td {
		border-bottom: none;
	}

	tr.editor td {
		padding: 0.75rem 0.6rem 1rem;
		background: var(--sunken);
	}

	.row-actions {
		display: flex;
		gap: 0.75rem;
	}

	button.link {
		font: inherit;
		border: none;
		background: none;
		padding: 0;
		color: var(--dim);
		text-decoration: underline;
		cursor: pointer;
	}

	.meta {
		color: var(--dim);
		font-size: 0.85rem;
	}

	tfoot th {
		border-top: 1px solid var(--ink);
	}

	/* What the block actually ends up with, the chosen options folded in. */
	.loadout {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.15rem 0.75rem;
		margin: 0.9rem 0 0;
		font-size: 0.85rem;

		dt {
			color: var(--dim);
		}

		dd {
			margin: 0;
		}
	}

	.unmodelled {
		color: var(--dim);
		text-decoration: underline dotted var(--line);
	}
</style>
