<script lang="ts">
	import BattleTable from '$lib/BattleTable.svelte';
	import Dock from '$lib/Dock.svelte';
	import Block from '$lib/Block.svelte';
	import Panes from '$lib/Panes.svelte';
	import Resolved from '$lib/Resolved.svelte';
	import Warn from '$lib/Warn.svelte';
	import { resolve } from '$app/paths';
	import { api, type FightBody, type MusteredUnit, type VolleyBody } from '$lib/api/client';
	import { battle } from '$lib/battle.svelte';
	import { entry } from '$lib/corpus';
	import { fielded, listing } from '$lib/listing';
	import {
		TABLE,
		arc,
		bounds,
		identifier,
		inside,
		refit,
		room,
		separation,
		span,
		usable,
		type Placed
	} from '$lib/table';

	type Reacting = NonNullable<FightBody['charge']>['reaction'];

	let { data } = $props();

	let panes = $state<Panes | null>(null);
	let needle = $state('');
	let picked = $state<number | null>(null);
	let refusal = $state('');
	let resolving = $state('');
	let menuWidth = $state(0);
	let reacting = $state(false);

	const fight = $derived(battle.resolved?.action === 'fight' ? battle.resolved.report : null);
	const volley = $derived(battle.resolved?.action === 'volley' ? battle.resolved.report : null);

	const rows = $derived(listing(data.units, needle, { column: 'name', descending: false }));

	const points = $derived(battle.placed.reduce((sum, each) => sum + each.block.points, 0));

	const pair = $derived.by(() => {
		const open = battle.asking;
		if (!open) return null;
		const mover = battle.placed.find((each) => each.id === open.mover);
		const target = battle.placed.find((each) => each.id === open.target);
		if (!mover || !target) return null;
		const box = bounds(target);
		const below = box.bottom / TABLE.depth < 0.6;
		return {
			mover,
			target,
			inches: Math.round(separation(mover, target)),
			into: arc(mover, target),
			shoots: usable(mover.block, 'missile').length > 0,
			below,
			left: (target.x / TABLE.width) * 100,
			top: ((below ? box.bottom : box.top) / TABLE.depth) * 100
		};
	});

	/** What the engine says the open pair can do: the chance the charge reaches, and the shots in range. */
	let reach = $state<{ charge: number | null; shots: number | null }>({
		charge: null,
		shots: null
	});
	$effect(() => {
		const open = pair;
		reach = { charge: null, shots: null };
		if (!open) return;
		let live = true;
		const client = api(window.location.origin, fetch);
		client
			.POST('/fight', {
				body: {
					a: deployment(open.mover, 'melee'),
					b: deployment(open.target, 'melee'),
					charge: { side: 'a', full_inches: open.inches, arc: open.into, reaction: 'hold' }
				}
			})
			.then(({ data }) => {
				if (live && data) reach = { ...reach, charge: data.p_charge_reaches ?? null };
			});
		if (open.shoots)
			client
				.POST('/volley', {
					body: {
						shooter: deployment(open.mover, 'missile'),
						target: deployment(open.target, 'melee'),
						distance: open.inches,
						moved: false
					}
				})
				.then(({ data }) => {
					if (live && data) reach = { ...reach, shots: data.shots };
				});
		return () => (live = false);
	});

	$effect(() => {
		void battle.asking;
		reacting = false;
	});

	const answers = $derived(!!pair && usable(pair.target.block, 'missile').length > 0);

	const short = $derived(reach.charge === 0);
	const blocked = $derived(
		!pair?.shoots ? 'no missile weapon' : reach.shots === 0 ? 'out of range' : ''
	);

	const notes = $derived([
		...new Set([...(fight?.not_modelled ?? []), ...(volley?.not_modelled ?? [])])
	]);

	const linked = $derived(
		battle.asking ??
			(battle.resolved
				? { mover: battle.resolved.between[0], target: battle.resolved.between[1] }
				: null)
	);

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
			options: block.block.options.map((option) => option.id),
			weapon: weapon || null,
			frontage: block.block.footprint?.files ?? null
		};
	}

	function cleared() {
		battle.resolved = null;
		refusal = '';
	}

	async function meet(charging: boolean, reaction: Reacting = 'hold') {
		if (!pair) return;
		cleared();
		resolving = 'melee';
		const between: [number, number] = [pair.mover.id, pair.target.id];
		const body: FightBody = {
			a: deployment(pair.mover, 'melee'),
			b: deployment(pair.target, 'melee'),
			charge: charging ? { side: 'a', full_inches: pair.inches, arc: pair.into, reaction } : null
		};
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/fight',
			{ body }
		);
		resolving = '';
		battle.asking = null;
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		battle.resolved = { action: 'fight', between, body, report };
	}

	async function loose() {
		if (!pair) return;
		cleared();
		resolving = 'shooting';
		const between: [number, number] = [pair.mover.id, pair.target.id];
		const body: VolleyBody = {
			shooter: deployment(pair.mover, 'missile'),
			target: deployment(pair.target, 'melee'),
			distance: pair.inches,
			moved: false
		};
		const { data: report, error: refused } = await api(window.location.origin, fetch).POST(
			'/volley',
			{ body }
		);
		resolving = '';
		battle.asking = null;
		if (!report) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		battle.resolved = { action: 'volley', between, body, report };
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
			id: battle.nextId,
			mark: identifier(battle.stamped),
			block: costed,
			x: where?.x ?? TABLE.width / 2,
			y: where?.y ?? TABLE.depth - 6,
			facing: 0,
			melee: '',
			missile: ''
		};
		const settled = room(wanted, battle.placed);
		battle.placed = [...battle.placed, settled];
		battle.nextId += 1;
		battle.stamped += 1;
		picked = settled.id;
	}

	/** Re-cost a standing block at a new size or set of options. */
	async function recost(id: number, size: number, options: string[]) {
		const standing = battle.placed.find((each) => each.id === id);
		if (!standing) return;
		const costed = await muster(standing.block.unit, size, options);
		const now = battle.placed.find((each) => each.id === id);
		if (!costed || !now) return;
		const { x, y } = refit(now, costed);
		battle.amend(id, { block: costed, x, y });
	}

	/** Turn a block about its centre, nudged back onto the table if a corner swings off it. */
	function turn(id: number, facing: number) {
		const standing = battle.placed.find((each) => each.id === id);
		if (!standing) return;
		const { x, y } = inside({ ...standing, facing });
		battle.amend(id, { facing, x, y });
	}

	/** Re-form a block to a new width, asking the engine for the footprint it takes. */
	async function reform(id: number, frontage: number) {
		const block = battle.placed.find((each) => each.id === id);
		if (!block) return;
		const { data: costed, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{
				body: {
					unit: block.block.unit,
					size: block.block.size,
					options: block.block.options.map((option) => option.id),
					frontage
				}
			}
		);
		if (!costed) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not re-form that';
			return;
		}
		const now = battle.placed.find((each) => each.id === id);
		if (!now) return;
		const { x, y } = refit(now, costed);
		battle.amend(id, { block: costed, x, y });
	}

	/** Open a block's own pane: the datasheet it fields, with what it is changed by beside it. */
	function sheet(id: number) {
		const standing = battle.placed.find((each) => each.id === id);
		if (!standing) return;
		panes?.show({
			subject: 'unit',
			slug: standing.block.unit,
			title: `${standing.mark} · ${standing.block.name}`,
			block: id
		});
	}

	/** Focus the reaction a charge is met with unless told otherwise, so Enter declares it. */
	function focused(node: HTMLButtonElement, on: boolean) {
		if (on) node.focus();
	}

	function remove(id: number) {
		battle.remove(id);
		panes?.forget(id);
		if (picked === id) picked = null;
	}
</script>

<svelte:window
	onkeydown={(event) => event.key === 'Escape' && battle.asking && (battle.asking = null)}
/>

<div class="tabletop">
	<aside class="left">
		<Dock
			title="deploy"
			keep="deploy"
			count={battle.placed.length}
			value={battle.placed.length ? `${points} pts` : ''}
		>
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
		<div class="surface" style="--aspect: {TABLE.width / TABLE.depth}">
			<BattleTable
				placed={battle.placed}
				{picked}
				{linked}
				onpick={(id) => (picked = id)}
				onmove={(id, x, y) => battle.amend(id, { x, y })}
				onturn={turn}
				ondrop={(mover, target) => {
					battle.asking = { mover, target };
				}}
				onreform={reform}
				ondropunit={(unit, size, x, y) => deploy(unit, size, { x, y })}
				onedit={(id) => ((picked = id), sheet(id))}
				onremove={remove}
			/>
			{#if pair}
				<div
					class="menu"
					class:above={!pair.below}
					bind:offsetWidth={menuWidth}
					style:left="clamp({menuWidth / 2}px, {pair.left}%, calc(100% - {menuWidth / 2}px))"
					style:top="{pair.top}%"
				>
					<span class="head">
						<span>{pair.mover.mark} → {pair.target.mark} · {pair.inches}in · {pair.into}</span>
						<button class="shut" aria-label="close" onclick={() => (battle.asking = null)}>×</button
						>
					</span>
					{#if reacting}
						<span class="cluster tight" role="group" aria-label="reaction">
							<span class="dimmed">
								<button
									class="btn btn-sm"
									class:btn-primary={answers}
									disabled={!answers}
									use:focused={answers}
									onclick={() => meet(true, 'stand-and-shoot')}>S&S</button
								>
								{#if !answers}<span class="says">no missile weapon</span>{/if}
							</span>
							<button
								class="btn btn-sm"
								class:btn-primary={!answers}
								use:focused={!answers}
								onclick={() => meet(true, 'hold')}>hold</button
							>
							<span class="dimmed">
								<button class="btn btn-sm" disabled>flee</button>
								<span class="says">not implemented in the engine</span>
							</span>
						</span>
					{:else}
						<span class="dimmed">
							<button
								class="btn btn-sm btn-primary"
								disabled={short}
								onclick={() => (reacting = true)}
							>
								charge
							</button>
							{#if short}<span class="says">out of charge range</span>{/if}
						</span>
						<span class="dimmed">
							<button class="btn btn-sm" disabled={!!blocked} onclick={loose}>shoot</button>
							{#if blocked}<span class="says">{blocked}</span>{/if}
						</span>
						{#if pair.inches === 0}
							<button class="btn btn-sm" onclick={() => meet(false)}>fight, engaged</button>
						{/if}
					{/if}
				</div>
			{/if}
		</div>
		{#if refusal}<p class="refuse">{refusal}</p>{/if}
	</div>

	<aside class="right">
		<Dock
			title="resolved"
			keep="resolved"
			value={resolving || (fight ? 'melee' : volley ? 'shooting' : '')}
		>
			{#snippet aside()}
				<Warn {notes} count />
				{#if fight || volley}
					<a class="btn btn-sm" href={resolve('/graph')}>graph →</a>
				{/if}
			{/snippet}
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
		{@const standing = battle.placed.find((each) => each.id === id)}
		{#if standing}
			<Block
				{standing}
				onrecost={(size, chosen) => recost(id, size, chosen)}
				onamend={(change) => battle.amend(id, change)}
				onreform={(files) => reform(id, files)}
				onturn={(facing) => turn(id, facing)}
				onremove={() => remove(id)}
			/>
		{/if}
	{/snippet}
</Panes>
