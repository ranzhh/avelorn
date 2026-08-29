<script lang="ts">
	import BattleTable from '$lib/BattleTable.svelte';
	import Conditions from '$lib/Conditions.svelte';
	import Dock from '$lib/Dock.svelte';
	import Muster from '$lib/Muster.svelte';
	import Panes from '$lib/Panes.svelte';
	import Resolved from '$lib/Resolved.svelte';
	import { api, type FightReport, type MusteredUnit, type VolleyReport } from '$lib/api/client';
	import { FRESH, strengthFor, summary, type Conditions as Held } from '$lib/conditions';
	import { entry } from '$lib/corpus';
	import { fielded, listing } from '$lib/listing';
	import { TABLE, arc, identifier, room, separation, span, usable, type Placed } from '$lib/table';

	let { data } = $props();

	let panes = $state<Panes | null>(null);
	let needle = $state('');
	let stamped = $state(0);
	let placed = $state<Placed[]>([]);
	let nextId = $state(1);
	let picked = $state<number | null>(null);
	let refusal = $state('');
	// The pair a menu is open on: what the first could do to the second.
	let asking = $state<{ mover: number; target: number } | null>(null);
	let resolving = $state('');
	let fight = $state<FightReport | null>(null);
	let volley = $state<VolleyReport | null>(null);
	let held = $state<Held>({ ...FRESH });
	// The volley on screen, kept so a change of conditions re-asks it rather
	// than leaving a stale answer under new premises.
	let asked = $state<{ shooter: number; target: number; inches: number } | null>(null);

	const rows = $derived(listing(data.units, needle, { column: 'name', descending: false }));

	const block = $derived(placed.find((each) => each.id === picked) ?? null);
	const shotAt = $derived(placed.find((each) => each.id === asked?.target) ?? null);
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

	// Footprints for the panel's drag image, costed once on hover so dragstart
	// has one to hand: it is synchronous and cannot wait for a round trip.
	const shapes: Record<string, MusteredUnit> = {};
	async function shape(unit: string, size: number) {
		if (shapes[unit]) return;
		const costed = await muster(unit, size, []);
		if (costed) shapes[unit] = costed;
	}

	/**
	 * Drag the block, not its name.
	 *
	 * The ghost under the pointer is the rectangle the unit will occupy, at the
	 * scale the table is drawn, so what lands is what was carried.
	 */
	function carry(event: DragEvent, unit: string, size: number) {
		event.dataTransfer?.setData('application/avelorn-unit', `${unit}:${size}`);
		const costed = shapes[unit];
		const print = costed?.footprint;
		const surface = document.querySelector('.surface svg');
		if (!print || !surface) return;
		const perInch = surface.getBoundingClientRect().width / TABLE.width;
		const { width, depth } = span(print);
		const ghost = document.createElement('div');
		ghost.className = 'carried';
		ghost.style.width = `${width * perInch}px`;
		ghost.style.height = `${depth * perInch}px`;
		ghost.textContent = `${print.files}×${print.ranks}`;
		document.body.append(ghost);
		event.dataTransfer?.setDragImage(ghost, (width * perInch) / 2, (depth * perInch) / 2);
		setTimeout(() => ghost.remove());
	}
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
		asked = { shooter: pair.mover.id, target: pair.target.id, inches: pair.inches };
		asking = null;
		await fire();
	}

	/** Resolve the volley on screen under the conditions currently held. */
	async function fire() {
		const shot = asked;
		if (!shot) return;
		const shooter = placed.find((each) => each.id === shot.shooter);
		const target = placed.find((each) => each.id === shot.target);
		if (!shooter || !target) return;
		cleared();
		resolving = 'shooting';
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/volley',
			{
				body: {
					shooter: deployment(shooter, 'missile'),
					target: deployment(target, 'melee'),
					distance: shot.inches,
					moved: held.moved,
					hit_modifier: held.hit,
					battle_strength: strengthFor(held.battleStrength, target.block.size)
				}
			}
		);
		resolving = '';
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		volley = report;
	}

	async function muster(unit: string, size: number, options: string[], frontage?: number) {
		refusal = '';
		const { data: costed, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit, size, options, frontage: frontage ?? null } }
		);
		if (!costed) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not cost that';
			return null;
		}
		if (!costed.footprint) {
			refusal = `${costed.name}: no base size, cannot be drawn`;
			return null;
		}
		return costed;
	}

	/**
	 * Put a datasheet on the table at its smallest legal size.
	 *
	 * Clicking a row deploys rather than opening a form: the block lands, and the
	 * size and options are then chosen against something you can see.
	 */
	async function deploy(unit: string, size: number, where?: { x: number; y: number }) {
		const costed = await muster(unit, size, []);
		if (!costed) return;
		const wanted: Placed = {
			id: nextId,
			mark: identifier(stamped),
			block: costed,
			x: where?.x ?? TABLE.width / 2,
			y: where?.y ?? TABLE.depth - 6,
			facing: 0,
			melee: '',
			missile: ''
		};
		const settled = room(wanted, placed);
		placed = [...placed, settled];
		nextId += 1;
		stamped += 1;
		picked = settled.id;
	}

	/** Re-cost a standing block at a new size or set of options. */
	async function recost(id: number, size: number, options: string[]) {
		const standing = placed.find((each) => each.id === id);
		if (!standing) return;
		const costed = await muster(standing.block.unit, size, options);
		if (!costed) return;
		amend(id, { block: costed });
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

	/** Open a block's own pane: the datasheet it fields, with its options beside it. */
	function sheet(id: number) {
		const standing = placed.find((each) => each.id === id);
		if (!standing) return;
		panes?.show({
			subject: 'unit',
			slug: standing.block.unit,
			title: `${standing.mark} · ${standing.block.name}`,
			block: id
		});
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
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="row"
						draggable="true"
						onpointerenter={() => {
							shape(unit.id, unit.unit_size.min);
							entry('unit', unit.id);
						}}
						ondragstart={(event) => carry(event, unit.id, unit.unit_size.min)}
					>
						<button class="pick" onclick={() => deploy(unit.id, unit.unit_size.min)}>
							<span>{unit.name}</span>
							<span class="cost num">
								<span class="least">×{unit.unit_size.min}</span>
								{fielded(unit)} pts
							</span>
						</button>
						<button
							class="sheet"
							title="datasheet"
							onclick={() => panes?.show({ subject: 'unit', slug: unit.id, title: unit.name })}
						>
							sheet
						</button>
					</div>
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
				ondropunit={(unit, size, x, y) => deploy(unit, size, { x, y })}
				onedit={(id) => ((picked = id), sheet(id))}
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
					<button class="btn btn-sm" onclick={() => sheet(block.id)}>datasheet</button>
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

		<Dock title="conditions" keep="conditions" value={summary(held)}>
			<Conditions
				conditions={held}
				size={shotAt?.block.size ?? null}
				onchange={(next) => {
					held = next;
					fire();
				}}
			/>
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

<Panes bind:this={panes}>
	{#snippet options(id)}
		{@const standing = placed.find((each) => each.id === id)}
		{#if standing}
			<Muster
				live
				unit={standing.block.unit}
				size={standing.block.size}
				options={standing.block.options}
				onsubmit={(size, chosen) => recost(id, size, chosen)}
			/>
		{/if}
	{/snippet}
</Panes>

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
		transform: translate(-50%, var(--space-4));
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
		align-items: center;
		border-radius: var(--radius-sm);
	}

	.row:hover {
		background: var(--panel);
	}

	.pick {
		display: flex;
		flex: 1;
		min-width: 0;
		justify-content: space-between;
		gap: var(--space-2);
		padding: 2px var(--space-2);
		font: inherit;
		font-size: var(--text-sm);
		color: var(--ink);
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
	}

	.pick span:first-child {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* Reading a datasheet is the second thing a row does, so it stays out of
	   the way until the row is under the pointer. */
	.sheet {
		flex: none;
		visibility: hidden;
		padding: 0 var(--space-2);
		font: var(--text-xs) / 1.6 var(--font-mono);
		color: var(--accent-ink);
		background: none;
		border: none;
		cursor: pointer;
	}

	.row:hover .sheet,
	.sheet:focus-visible {
		visibility: visible;
	}

	.cost {
		color: var(--dim);
		white-space: nowrap;
	}

	.least {
		color: var(--faint);
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
