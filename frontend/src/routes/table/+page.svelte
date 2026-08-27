<script lang="ts">
	import BattleTable from '$lib/BattleTable.svelte';
	import Dock from '$lib/Dock.svelte';
	import Muster from '$lib/Muster.svelte';
	import Resolved from '$lib/Resolved.svelte';
	import { api, type FightReport, type VolleyReport } from '$lib/api/client';
	import { listing } from '$lib/listing';
	import { TABLE, arc, room, separation, usable, type Placed } from '$lib/table';

	let { data } = $props();

	let needle = $state('');
	let opened = $state('');
	let placed = $state<Placed[]>([]);
	let nextId = $state(1);
	let picked = $state<number | null>(null);
	let refusal = $state('');
	// The pair a menu is open on: what the first could do to the second.
	let asking = $state<{ mover: number; target: number } | null>(null);
	let resolving = $state('');
	let fight = $state<FightReport | null>(null);
	let volley = $state<VolleyReport | null>(null);

	const rows = $derived(listing(data.units, needle, { column: 'name', descending: false }));
	const block = $derived(placed.find((each) => each.id === picked) ?? null);
	const points = $derived(placed.reduce((sum, each) => sum + each.block.points, 0));

	const pair = $derived.by(() => {
		const open = asking;
		if (!open) return null;
		const mover = placed.find((each) => each.id === open.mover);
		const target = placed.find((each) => each.id === open.target);
		if (!mover || !target) return null;
		return {
			mover,
			target,
			inches: Math.round(separation(mover, target)),
			into: arc(mover, target),
			shoots: usable(mover.block, 'missile').length > 0
		};
	});

	function deployment(block: Placed, phase: 'melee' | 'missile') {
		const weapon = phase === 'melee' ? block.melee : block.missile;
		return {
			unit: block.block.unit,
			size: block.block.size,
			options: block.block.options,
			weapon: weapon || null,
			frontage: block.block.footprint?.files ?? null
		};
	}

	function cleared() {
		fight = null;
		volley = null;
		refusal = '';
	}

	async function meet(charging: boolean) {
		if (!pair) return;
		cleared();
		resolving = 'melee';
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/fight',
			{
				body: {
					a: deployment(pair.mover, 'melee'),
					b: deployment(pair.target, 'melee'),
					charge: charging ? { side: 'a', full_inches: pair.inches, arc: pair.into } : null
				}
			}
		);
		resolving = '';
		asking = null;
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		fight = report;
	}

	async function loose() {
		if (!pair) return;
		cleared();
		resolving = 'shooting';
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/volley',
			{
				body: {
					shooter: deployment(pair.mover, 'missile'),
					target: deployment(pair.target, 'melee'),
					distance: pair.inches,
					hit_modifier: 0
				}
			}
		);
		resolving = '';
		asking = null;
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		volley = report;
	}

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
		// Deployed on the near edge, facing up the table, then dragged from there.
		const wanted: Placed = {
			id: nextId,
			block: costed,
			x: TABLE.width / 2,
			y: TABLE.depth - 6,
			facing: 0,
			melee: '',
			missile: ''
		};
		const settled = room(wanted, placed);
		placed = [...placed, settled];
		nextId += 1;
		picked = settled.id;
		opened = '';
	}

	/** Re-form a block to a new width, asking the engine for the footprint it takes. */
	async function reform(id: number, frontage: number) {
		const block = placed.find((each) => each.id === id);
		if (!block) return;
		const { data: costed, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{
				body: {
					unit: block.block.unit,
					size: block.block.size,
					options: block.block.options,
					frontage
				}
			}
		);
		if (!costed) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not re-form that';
			return;
		}
		amend(id, { block: costed });
	}

	function amend(id: number, change: Partial<Placed>) {
		placed = placed.map((each) => (each.id === id ? { ...each, ...change } : each));
	}

	function remove(id: number) {
		placed = placed.filter((each) => each.id !== id);
		if (picked === id) picked = null;
	}
</script>

<div class="shell">
	<aside class="left">
		<Dock title="deploy" keep="deploy" value={`${placed.length} on the table`}>
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
		<div class="surface">
			<BattleTable
				{placed}
				{picked}
				onpick={(id) => (picked = id)}
				onmove={(id, x, y) => amend(id, { x, y })}
				onturn={(id, facing) => amend(id, { facing })}
				ondrop={(mover, target) => (asking = { mover, target })}
				onreform={reform}
			/>
			{#if pair}
				<div
					class="menu"
					style="left: {(pair.target.x / TABLE.width) * 100}%; top: {(pair.target.y / TABLE.depth) *
						100}%"
				>
					<span class="head">{pair.inches}in · {pair.into}</span>
					<button class="btn btn-sm btn-primary" onclick={() => meet(true)}>
						charge {pair.inches}in
					</button>
					<button class="btn btn-sm" disabled={!pair.shoots} onclick={loose}>
						{pair.shoots ? `shoot at ${pair.inches}in` : 'no missile weapon'}
					</button>
					<button class="btn btn-sm" onclick={() => meet(false)}>fight, engaged</button>
					<button class="btn btn-ghost btn-sm" onclick={() => (asking = null)}>cancel</button>
				</div>
			{/if}
		</div>
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
					<button class="btn btn-sm" onclick={() => amend(block.id, { facing: 0 })}>
						face up
					</button>
					<button class="btn btn-sm" onclick={() => remove(block.id)}>remove</button>
				</div>
			{:else}
				<div class="field"><span>blocks</span><span class="num">{placed.length}</span></div>
				<div class="field"><span>points</span><span class="num">{points}</span></div>
			{/if}
		</Dock>

		<Dock
			title="resolved"
			keep="resolved"
			value={resolving || (fight ? 'melee' : volley ? 'shooting' : '')}
		>
			{#if resolving}
				<p class="pending">{resolving}…</p>
			{:else if fight || volley}
				<Resolved {fight} {volley} />
			{/if}
		</Dock>
	</aside>
</div>

<style>
	.shell {
		display: grid;
		grid-template-columns: 16rem minmax(0, 1fr) 19rem;
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

	.surface {
		position: relative;
	}

	.menu {
		position: absolute;
		transform: translate(-50%, var(--space-2));
		z-index: 2;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2);
		background: var(--panel);
		border: 1px solid var(--faint);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow);
	}

	.menu .head {
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
		padding: 0 var(--space-1);
	}

	.pending {
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
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
