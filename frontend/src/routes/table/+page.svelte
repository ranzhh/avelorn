<script lang="ts">
	import FightOutcome from '$lib/FightOutcome.svelte';
	import Muster from '$lib/Muster.svelte';
	import VolleyOutcome from '$lib/VolleyOutcome.svelte';
	import {
		api,
		type FightReport,
		type MusteredUnit,
		type UnitSummary,
		type VolleyReport
	} from '$lib/api/client';
	import {
		TABLE,
		arc,
		extent,
		separation,
		usable,
		within,
		type Facing,
		type Placed
	} from '$lib/table';

	const ROSTER_KEY = 'avelorn:list';

	let { data } = $props();

	let roster = $state<MusteredUnit[]>([]);
	let placed = $state<Placed[]>([]);
	let nextId = $state(1);

	// The datasheet whose muster form is open in the browser, if any.
	let opened = $state('');
	// A costed block waiting for somewhere to stand.
	let pending = $state<MusteredUnit | null>(null);
	let mover = $state<number | null>(null);
	// The target a menu is open against: what the mover could do to it.
	let asking = $state<number | null>(null);

	let refusal = $state('');
	let resolving = $state('');
	let fought = $state<FightReport | null>(null);
	let volleyed = $state<VolleyReport | null>(null);

	$effect(() => {
		const saved = localStorage.getItem(ROSTER_KEY);
		if (saved) roster = JSON.parse(saved);
	});

	const armies = $derived.by(() => {
		const filed: Record<string, UnitSummary[]> = {};
		for (const unit of data.units) {
			for (const army of unit.armies) (filed[army] ??= []).push(unit);
		}
		return Object.entries(filed).sort(([one], [two]) => one.localeCompare(two));
	});

	// A foot apart, the interior lines only: the border draws the table's edge.
	const ruled = (span: number) =>
		[...Array(Math.floor(span / 12) - 1).keys()].map((n) => (n + 1) * 12);
	const columns = ruled(TABLE.width);
	const rows = ruled(TABLE.depth);

	// No army entry in the corpus carries a printed name, only the directory it
	// is filed under, so the heading is that slug read back as words.
	const titled = (slug: string) =>
		slug
			.split('-')
			.map((word) => word[0].toUpperCase() + word.slice(1))
			.join(' ');

	const chosen = $derived(placed.find((each) => each.id === mover) ?? null);
	const target = $derived(placed.find((each) => each.id === asking) ?? null);

	// What the geometry says about the pair a menu is open on, which is what the
	// engine would otherwise have to be told.
	const approach = $derived.by(() => {
		if (!chosen || !target) return null;
		return {
			inches: Math.round(separation(chosen, target)),
			into: arc(chosen, target),
			shoots: usable(chosen.block, 'missile').length > 0
		};
	});

	async function cost(unit: string, size: number, options: string[]): Promise<MusteredUnit | null> {
		refusal = '';
		const { data: block, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit, size, options } }
		);
		if (!block) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not cost that';
			return null;
		}
		return block;
	}

	async function deploy(unit: string, size: number, options: string[]) {
		const block = await cost(unit, size, options);
		if (!block) return;
		if (!block.footprint) {
			refusal = `${block.name} prints no base size, so it cannot be put on the table`;
			return;
		}
		pending = block;
		opened = '';
	}

	// A list entry is re-costed on its way to the table rather than deployed as
	// it was saved: the roster is persisted in the browser, so an entry may
	// predate anything the API has since learned to say about a block.
	async function deployFromList(entry: MusteredUnit) {
		await deploy(entry.unit, entry.size, entry.options);
	}

	async function addToList(unit: string, size: number, options: string[]) {
		const block = await cost(unit, size, options);
		if (!block) return;
		roster = [...roster, block];
		localStorage.setItem(ROSTER_KEY, JSON.stringify(roster));
		opened = '';
	}

	function put(block: MusteredUnit, x: number, y: number) {
		// Facing the middle of the table, which is where the other side is.
		const candidate: Placed = {
			id: nextId,
			block,
			x,
			y,
			facing: y > TABLE.depth / 2 ? 0 : 180,
			melee: '',
			missile: ''
		};
		if (!within(candidate)) {
			refusal = `${block.name} would hang off the table there`;
			return;
		}
		placed = [...placed, candidate];
		nextId += 1;
		pending = null;
		refusal = '';
	}

	function onTable(event: MouseEvent) {
		const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
		const x = ((event.clientX - box.left) / box.width) * TABLE.width;
		const y = ((event.clientY - box.top) / box.height) * TABLE.depth;
		if (pending) {
			put(pending, x, y);
			return;
		}
		mover = null;
		asking = null;
	}

	function onBlock(id: number) {
		if (pending) return;
		asking = null;
		if (mover === null || mover === id) {
			mover = mover === id ? null : id;
			return;
		}
		asking = id;
	}

	function rotate(id: number) {
		placed = placed.map((each) =>
			each.id === id ? { ...each, facing: ((each.facing + 90) % 360) as Facing } : each
		);
	}

	function remove(id: number) {
		placed = placed.filter((each) => each.id !== id);
		if (mover === id) mover = null;
		if (asking === id) asking = null;
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

	function clear() {
		fought = null;
		volleyed = null;
		refusal = '';
	}

	async function meet(charging: boolean) {
		if (!chosen || !target || !approach) return;
		clear();
		resolving = 'fight';
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/fight',
			{
				body: {
					a: deployment(chosen, 'melee'),
					b: deployment(target, 'melee'),
					charge: charging ? { side: 'a', full_inches: approach.inches, arc: approach.into } : null
				}
			}
		);
		resolving = '';
		asking = null;
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		fought = report;
	}

	async function loose() {
		if (!chosen || !target || !approach) return;
		clear();
		resolving = 'volley';
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/volley',
			{
				body: {
					shooter: deployment(chosen, 'missile'),
					target: deployment(target, 'melee'),
					distance: approach.inches,
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
		volleyed = report;
	}
</script>

<div class="screen">
	<aside>
		<h1>Deploy</h1>

		{#if roster.length}
			<section class="roster">
				<h2>Your list</h2>
				{#each roster as block}
					<div class="entry">
						<span>{block.name} × {block.size} <span class="meta">{block.points} pts</span></span>
						<button class="link" onclick={() => deployFromList(block)}>deploy</button>
					</div>
				{/each}
			</section>
		{/if}

		{#each armies as [army, units]}
			<section>
				<h2>{titled(army)}</h2>
				{#each units as unit}
					<div class="entry">
						<button class="link name" onclick={() => (opened = opened === unit.id ? '' : unit.id)}>
							{unit.name}
						</button>
						<span class="meta">{unit.points} pts</span>
					</div>
					{#if opened === unit.id}
						<Muster
							unit={unit.id}
							size={unit.unit_size.min}
							options={[]}
							submitLabel="Deploy"
							alsoLabel="Add to list"
							onsubmit={(size, options) => deploy(unit.id, size, options)}
							onalso={(size, options) => addToList(unit.id, size, options)}
							oncancel={() => (opened = '')}
						/>
					{/if}
				{/each}
			</section>
		{/each}
	</aside>

	<div class="battle">
		<p class="meta hint">
			{#if pending}
				Click the table to put {pending.name} down.
			{:else if chosen && !target}
				{chosen.block.name} is picked up. Click another block to see what it could do to it.
			{:else if placed.length === 0}
				Pick a datasheet on the left, size it, and deploy it. The rectangle is what it occupies.
			{:else}
				Click a block to pick it, then click another. Distances and arcs come off the table.
			{/if}
		</p>

		<div class="table-wrap">
			<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
			<svg
				viewBox="0 0 {TABLE.width} {TABLE.depth}"
				class:placing={pending !== null}
				onclick={onTable}
			>
				<rect class="cloth" x="0" y="0" width={TABLE.width} height={TABLE.depth} />
				{#each columns as inches}
					<line class="foot" x1={inches} y1="0" x2={inches} y2={TABLE.depth} />
				{/each}
				{#each rows as inches}
					<line class="foot" x1="0" y1={inches} x2={TABLE.width} y2={inches} />
				{/each}

				{#each placed as block (block.id)}
					{@const box = extent(block)}
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<g
						class="block"
						class:picked={block.id === mover}
						class:asked={block.id === asking}
						onclick={(event) => {
							event.stopPropagation();
							onBlock(block.id);
						}}
					>
						<rect x={box.left} y={box.top} width={box.width} height={box.height} />
						{#if block.facing === 0}
							<line x1={box.left} y1={box.top} x2={box.right} y2={box.top} class="front" />
						{:else if block.facing === 180}
							<line x1={box.left} y1={box.bottom} x2={box.right} y2={box.bottom} class="front" />
						{:else if block.facing === 90}
							<line x1={box.right} y1={box.top} x2={box.right} y2={box.bottom} class="front" />
						{:else}
							<line x1={box.left} y1={box.top} x2={box.left} y2={box.bottom} class="front" />
						{/if}
						<text x={block.x} y={block.y + 0.5}>{block.block.size}</text>
					</g>
				{/each}
			</svg>

			{#if target && approach}
				<div
					class="menu"
					style="left: {(target.x / TABLE.width) * 100}%; top: {(target.y / TABLE.depth) * 100}%"
				>
					<p class="meta">
						{approach.inches}″ away, into its {approach.into}
					</p>
					<button disabled={resolving !== ''} onclick={() => meet(true)}>
						Charge {approach.inches}″ into the {approach.into}
					</button>
					<button disabled={resolving !== '' || !approach.shoots} onclick={loose}>
						{approach.shoots ? `Shoot at ${approach.inches}″` : 'Nothing to shoot with'}
					</button>
					<button disabled={resolving !== ''} onclick={() => meet(false)}>
						Fight, already engaged
					</button>
					<button class="link" onclick={() => (asking = null)}>cancel</button>
				</div>
			{/if}
		</div>

		{#if chosen}
			<div class="inspector">
				<strong>{chosen.block.name}</strong>
				<span class="meta">
					× {chosen.block.size} · {chosen.block.footprint?.files} wide, {chosen.block.footprint
						?.ranks} deep · facing {chosen.facing}°
				</span>
				{#if usable(chosen.block, 'melee').length > 1}
					<label>
						fights with
						<select
							value={chosen.melee}
							onchange={(e) =>
								(placed = placed.map((each) =>
									each.id === chosen.id ? { ...each, melee: e.currentTarget.value } : each
								))}
						>
							<option value="">the datasheet's pick</option>
							{#each usable(chosen.block, 'melee') as weapon}
								<option value={weapon.name}>{weapon.name}</option>
							{/each}
						</select>
					</label>
				{/if}
				{#if usable(chosen.block, 'missile').length > 1}
					<label>
						shoots with
						<select
							value={chosen.missile}
							onchange={(e) =>
								(placed = placed.map((each) =>
									each.id === chosen.id ? { ...each, missile: e.currentTarget.value } : each
								))}
						>
							<option value="">the datasheet's pick</option>
							{#each usable(chosen.block, 'missile') as weapon}
								<option value={weapon.name}>{weapon.name}</option>
							{/each}
						</select>
					</label>
				{/if}
				<button onclick={() => rotate(chosen.id)}>wheel a quarter</button>
				<button onclick={() => remove(chosen.id)}>take off</button>
			</div>
		{/if}

		{#if refusal}<p class="refusal">{refusal}</p>{/if}
		{#if resolving}<p class="meta">Resolving…</p>{/if}

		{#if fought}
			<div class="outcome"><FightOutcome report={fought} /></div>
		{:else if volleyed}
			<div class="outcome"><VolleyOutcome report={volleyed} /></div>
		{/if}
	</div>
</div>

<style>
	/*
	 * The table before the browser on a narrow screen. Side by side, a 20rem
	 * panel leaves a phone nothing to put the table in, and the table is the
	 * thing being pointed at.
	 */
	.screen {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.battle {
		order: -1;
	}

	aside {
		border-top: 1px solid var(--rule);
		padding-top: 1rem;
	}

	@media (min-width: 60rem) {
		.screen {
			display: grid;
			grid-template-columns: 20rem 1fr;
			align-items: start;
		}

		.battle {
			order: initial;
		}

		aside {
			border-top: none;
			padding-top: 0;
			border-right: 1px solid var(--rule);
			padding-right: 1rem;
			max-height: calc(100vh - 6rem);
			overflow-y: auto;
		}
	}

	h1 {
		font-size: 1.2rem;
		margin: 0 0 1rem;
	}

	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted);
		margin: 1rem 0 0.4rem;
	}

	.entry {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 0.5rem;
		font-size: 0.9rem;
		padding: 0.15rem 0;
	}

	.roster .entry {
		border-bottom: 1px dotted var(--rule);
	}

	.hint {
		min-height: 1.5rem;
	}

	.table-wrap {
		position: relative;
	}

	svg {
		display: block;
		width: 100%;
		border: 1px solid var(--rule);
		border-radius: 3px;
	}

	svg.placing {
		cursor: crosshair;
	}

	.cloth {
		fill: #f2ede3;
	}

	.foot {
		stroke: var(--rule);
		stroke-width: 0.08;
	}

	.block rect {
		fill: #cfd8d2;
		stroke: var(--ink);
		stroke-width: 0.12;
		cursor: pointer;
	}

	.block .front {
		stroke: var(--ink);
		stroke-width: 0.45;
	}

	.block text {
		font-size: 1.6px;
		text-anchor: middle;
		fill: var(--ink);
		pointer-events: none;
	}

	.block.picked rect {
		fill: #b9cbbf;
		stroke-width: 0.3;
	}

	.block.asked rect {
		fill: #e2cdc0;
		stroke-width: 0.3;
	}

	.menu {
		position: absolute;
		transform: translate(-50%, 0.5rem);
		max-width: min(15rem, 70vw);
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		padding: 0.6rem;
		background: var(--paper);
		border: 1px solid var(--ink);
		border-radius: 3px;
		box-shadow: 0 2px 8px rgb(0 0 0 / 0.15);
		font-size: 0.9rem;
		z-index: 1;
	}

	.menu p {
		margin: 0 0 0.2rem;
	}

	.inspector {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
		margin-top: 0.75rem;
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		font-size: 0.9rem;
	}

	.outcome {
		margin-top: 1.5rem;
		border-top: 1px solid var(--rule);
		padding-top: 1rem;
	}

	label {
		display: inline-flex;
		gap: 0.4rem;
		align-items: baseline;
	}

	select {
		font: inherit;
		font-size: 0.9rem;
		padding: 0.2rem 0.4rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
	}

	button {
		font: inherit;
		font-size: 0.9rem;
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
		cursor: pointer;
		text-align: left;
	}

	button:disabled {
		color: var(--muted);
		cursor: not-allowed;
	}

	button.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--muted);
		text-decoration: underline;
	}

	button.name {
		color: var(--ink);
		text-decoration: none;
	}

	button.name:hover {
		text-decoration: underline;
	}

	.meta {
		color: var(--muted);
		font-size: 0.85rem;
	}

	.refusal {
		color: #8a1c1c;
		font-size: 0.9rem;
	}
</style>
