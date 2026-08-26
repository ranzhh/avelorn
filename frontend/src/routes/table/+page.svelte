<script lang="ts">
	import BattleTable from '$lib/BattleTable.svelte';
	import Dock from '$lib/Dock.svelte';
	import Muster from '$lib/Muster.svelte';
	import { api, type MusteredUnit } from '$lib/api/client';
	import { listing } from '$lib/listing';
	import { TABLE, usable, within, type Facing, type Placed } from '$lib/table';

	let { data } = $props();

	let needle = $state('');
	let opened = $state('');
	let placed = $state<Placed[]>([]);
	let nextId = $state(1);
	let pending = $state<MusteredUnit | null>(null);
	let picked = $state<number | null>(null);
	let refusal = $state('');

	const rows = $derived(listing(data.units, needle, { column: 'name', descending: false }));
	const block = $derived(placed.find((each) => each.id === picked) ?? null);
	const points = $derived(placed.reduce((sum, each) => sum + each.block.points, 0));

	async function cost(unit: string, size: number, options: string[]) {
		refusal = '';
		const { data: costed, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit, size, options } }
		);
		if (!costed) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not cost that';
			return;
		}
		if (!costed.footprint) {
			refusal = `${costed.name}: no base size, cannot be drawn`;
			return;
		}
		pending = costed;
		opened = '';
	}

	function put(x: number, y: number) {
		if (!pending) return;
		// Facing the middle of the table, which is where the other side stands.
		const candidate: Placed = {
			id: nextId,
			block: pending,
			x,
			y,
			facing: y > TABLE.depth / 2 ? 0 : 180,
			melee: '',
			missile: ''
		};
		if (!within(candidate)) {
			refusal = `${pending.name}: off the table there`;
			return;
		}
		placed = [...placed, candidate];
		nextId += 1;
		picked = candidate.id;
		pending = null;
		refusal = '';
	}

	function amend(id: number, change: Partial<Placed>) {
		placed = placed.map((each) => (each.id === id ? { ...each, ...change } : each));
	}

	function wheel(id: number, facing: Facing) {
		amend(id, { facing: ((facing + 90) % 360) as Facing });
	}

	function remove(id: number) {
		placed = placed.filter((each) => each.id !== id);
		if (picked === id) picked = null;
	}
</script>

<div class="shell">
	<aside class="left">
		<Dock title="deploy" keep="deploy" value={pending ? `placing ${pending.name}` : ''}>
			<input class="input filter" bind:value={needle} placeholder="filter" />
			<div class="rows">
				{#each rows as unit (unit.id)}
					<button
						class="row"
						class:on={opened === unit.id}
						onclick={() => (opened = opened === unit.id ? '' : unit.id)}
					>
						<span>{unit.name}</span>
						<span class="num">{unit.points}</span>
					</button>
					{#if opened === unit.id}
						<div class="editor">
							<Muster
								unit={unit.id}
								size={unit.unit_size.min}
								options={[]}
								submitLabel="deploy"
								onsubmit={(size, options) => cost(unit.id, size, options)}
								oncancel={() => (opened = '')}
							/>
						</div>
					{/if}
				{/each}
			</div>
		</Dock>
	</aside>

	<div class="centre">
		<BattleTable
			{placed}
			{picked}
			placing={pending !== null}
			onplace={put}
			onpick={(id) => (picked = id)}
		/>
		{#if refusal}<p class="refuse">{refusal}</p>{/if}
	</div>

	<aside class="right">
		<Dock
			title="block"
			keep="block"
			value={block ? `${block.block.name} ×${block.block.size}` : ''}
		>
			{#if block}
				{@const print = block.block.footprint}
				<div class="field"><span>unit</span><span>{block.block.name}</span></div>
				<div class="field"><span>models</span><span class="num">{block.block.size}</span></div>
				<div class="field"><span>points</span><span class="num">{block.block.points}</span></div>
				{#if print}
					<div class="field">
						<span>formation</span><span class="num">{print.files}×{print.ranks}</span>
					</div>
					<div class="field">
						<span>footprint</span><span class="num">{print.width_mm}×{print.depth_mm} mm</span>
					</div>
				{/if}
				<div class="field"><span>facing</span><span class="num">{block.facing}°</span></div>
				{#if usable(block.block, 'melee').length > 1}
					<label class="field">
						<span>melee</span>
						<select
							class="select"
							value={block.melee}
							onchange={(e) => amend(block.id, { melee: e.currentTarget.value })}
						>
							<option value="">default</option>
							{#each usable(block.block, 'melee') as weapon}
								<option value={weapon.name}>{weapon.name}</option>
							{/each}
						</select>
					</label>
				{/if}
				{#if usable(block.block, 'missile').length > 1}
					<label class="field">
						<span>missile</span>
						<select
							class="select"
							value={block.missile}
							onchange={(e) => amend(block.id, { missile: e.currentTarget.value })}
						>
							<option value="">default</option>
							{#each usable(block.block, 'missile') as weapon}
								<option value={weapon.name}>{weapon.name}</option>
							{/each}
						</select>
					</label>
				{/if}
				<div class="cluster acts">
					<button class="btn btn-sm" onclick={() => wheel(block.id, block.facing)}>wheel</button>
					<button class="btn btn-sm" onclick={() => remove(block.id)}>remove</button>
				</div>
			{:else}
				<div class="field"><span>blocks</span><span class="num">{placed.length}</span></div>
				<div class="field"><span>points</span><span class="num">{points}</span></div>
			{/if}
		</Dock>
	</aside>
</div>

<style>
	.shell {
		display: grid;
		grid-template-columns: 17rem minmax(0, 1fr) 15rem;
		gap: 1px;
		background: var(--line);
		min-height: calc(100vh - 2.4rem);
	}

	aside {
		background: var(--plane);
	}

	.centre {
		background: var(--plane);
		padding: var(--space-3);
	}

	.filter {
		width: 100%;
		margin-bottom: var(--space-2);
	}

	.rows {
		max-height: 60vh;
		overflow-y: auto;
	}

	.row {
		display: flex;
		width: 100%;
		justify-content: space-between;
		gap: var(--space-2);
		padding: 2px var(--space-2);
		font: inherit;
		font-size: var(--text-sm);
		color: var(--ink);
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		text-align: left;
	}

	.row:hover {
		background: var(--panel);
	}

	.row.on {
		background: var(--panel);
		color: var(--accent-ink);
	}

	.row .num {
		color: var(--dim);
	}

	.editor {
		padding: var(--space-2);
		margin: var(--space-1) 0 var(--space-2);
		background: var(--panel);
		border-radius: var(--radius-sm);
	}

	.field span:first-child {
		color: var(--dim);
	}

	.field span:last-child {
		color: var(--ink);
	}

	.acts {
		margin-top: var(--space-3);
		gap: var(--space-2);
	}

	.refuse {
		margin-top: var(--space-2);
	}
</style>
