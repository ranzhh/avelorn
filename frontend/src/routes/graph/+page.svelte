<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, type FightBody, type FightLanes, type VolleyBody } from '$lib/api/client';
	import { battle } from '$lib/battle.svelte';
	import Fight from '$lib/fight/Fight.svelte';
	import { seat } from '$lib/fight/body';
	import { LANES } from '$lib/fight/faces';
	import { cropped, formed, measured, seated, type Blocks } from '$lib/fight/field';
	import type { Mode } from '$lib/fight/Settings.svelte';
	import type { Placed } from '$lib/table';
	import Graph from '$lib/graph/Graph.svelte';
	import type { Program } from '$lib/graph/types';

	/** Ask for the program the table's last volley ran on, posting the body it sent. */
	async function volley(body: VolleyBody): Promise<Program> {
		const { data: program, error: refused } = await api(page.url.origin, fetch).POST(
			'/graph/volley',
			{ body }
		);
		if (!program) {
			throw new Error(typeof refused?.detail === 'string' ? refused.detail : 'could not draw that');
		}
		return program as unknown as Program;
	}

	const last = $derived(battle.resolved);
	const matchup = $derived.by(() => {
		if (last?.action === 'fight') {
			const { a, b } = last.report;
			const charge = last.body.charge;
			const verb = charge ? 'charge' : 'fight';
			const range = charge ? ` at ${charge.full_inches}in` : '';
			return `${a.name} ×${a.size} ${verb} ${b.name} ×${b.size}${range}`;
		}
		if (last?.action === 'volley') {
			const { shooter, target } = last.report;
			return `${shooter.name} ×${shooter.size} shoot ${target.name} ×${target.size} at ${last.body.distance}in`;
		}
		return '';
	});
	const program = $derived(last?.action === 'volley' ? volley(last.body) : null);

	let body = $derived<FightBody | null>(
		last?.action === 'fight' ? $state.snapshot(last.body) : null
	);
	const seed = $derived(
		last?.action === 'fight'
			? seated(last.body, last.between, $state.snapshot(battle.placed))
			: null
	);
	let blocks = $derived(seed);
	let lanes = $state<FightLanes | null>(null);
	let refusal = $state('');
	let pending = $state(false);
	let asked = 0;

	const MODE_KEY = 'avelorn:graph:mode';
	let mode = $state<Mode>('edit');
	$effect(() => {
		const saved = untrack(() => localStorage.getItem(MODE_KEY));
		if (saved === 'preview' || saved === 'edit') mode = saved;
	});
	$effect(() => {
		localStorage.setItem(MODE_KEY, mode);
	});

	/**
	 * Write a body the graph drew back onto the table: each block re-costed as
	 * it is now fielded, standing where the battlefield left it, and the fight
	 * resolved again so the table's result is this one.
	 */
	async function commit(sent: FightBody, at: Blocks | null, ask: number) {
		const open = battle.resolved;
		if (open?.action !== 'fight') return;
		const client = api(page.url.origin, fetch);
		const next: Placed[] = [];
		for (const [index, side] of (['a', 'b'] as const).entries()) {
			const standing = battle.placed.find((each) => each.id === open.between[index]);
			if (!standing) return;
			const wanted = sent[side];
			const files = wanted.frontage ?? standing.block.footprint?.files ?? null;
			const options = wanted.options ?? [];
			const same =
				wanted.size === standing.block.size &&
				files === (standing.block.footprint?.files ?? null) &&
				options.join() === standing.block.options.map((option) => option.id).join();
			let block = standing.block;
			if (!same) {
				const { data: costed } = await client.POST('/muster', {
					body: { unit: wanted.unit, size: wanted.size, options, frontage: files }
				});
				if (!costed) return;
				block = costed;
			}
			const lane = LANES.find((each) => seat(sent, each) === side)!;
			const where = at?.[lane] ?? standing;
			next.push({
				...standing,
				block,
				melee: wanted.weapon ?? '',
				x: where.x,
				y: where.y,
				facing: where.facing
			});
		}
		const { data: report } = await client.POST('/fight', { body: sent });
		if (!report || ask !== asked) return;
		battle.placed = battle.placed.map((each) => next.find((one) => one.id === each.id) ?? each);
		battle.resolved = { action: 'fight', between: open.between, body: sent, report };
	}

	function moved(at: Blocks | null): boolean {
		const placed = seed;
		if (!at || !placed) return false;
		return LANES.some(
			(lane) =>
				at[lane].x !== placed[lane].x ||
				at[lane].y !== placed[lane].y ||
				at[lane].facing !== placed[lane].facing
		);
	}

	const field = $derived(
		seed &&
			blocks &&
			lanes && {
				blocks: {
					attacker: formed(blocks.attacker, lanes.units.attacker),
					target: formed(blocks.target, lanes.units.target)
				},
				crop: cropped(seed)
			}
	);

	$effect(() => {
		const charge = body?.charge;
		if (!body || !charge || !field) return;
		const { full_inches, arc } = measured(field.blocks);
		if (charge.full_inches !== full_inches || charge.arc !== arc)
			body = { ...body, charge: { ...charge, full_inches, arc } };
	});

	$effect(() => {
		const sent = body;
		if (!sent) return;
		const ask = ++asked;
		pending = true;
		const wait = setTimeout(
			async () => {
				const { data, error: refused } = await api(page.url.origin, fetch).POST('/graph/fight', {
					body: sent
				});
				if (ask !== asked) return;
				pending = false;
				refusal = data
					? ''
					: typeof refused?.detail === 'string'
						? refused.detail
						: 'could not draw that';
				if (!data) return;
				lanes = data;
				const at = untrack(() => blocks);
				const changed =
					last?.action === 'fight' &&
					(JSON.stringify(sent) !== JSON.stringify(last.body) || untrack(() => moved(at)));
				if (untrack(() => mode) === 'edit' && changed) commit(sent, at, ask);
			},
			untrack(() => lanes) ? 250 : 0
		);
		return () => clearTimeout(wait);
	});
</script>

<div class="matchup">
	<a class="btn btn-sm" href={resolve('/table')}>← table</a>
	{#if matchup}<span>{matchup}</span>{/if}
</div>

{#if last?.action === 'fight' && body}
	{#if refusal}<p class="refuse">{refusal}</p>{/if}
	{#if lanes}
		<Fight
			{lanes}
			{body}
			stale={pending || !!refusal}
			bind:mode
			{field}
			onedit={(next) => (body = next)}
			onmove={(lane, block) => blocks && (blocks = { ...blocks, [lane]: block })}
		/>
	{/if}
{:else if last?.action === 'volley' && program}
	{#await program}
		<p class="meta">drawing…</p>
	{:then program}
		<Graph {program} />
	{:catch refused}
		<p class="refuse">{refused.message}</p>
	{/await}
{/if}
