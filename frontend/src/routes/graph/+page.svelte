<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import {
		api,
		type FightBody,
		type FightLanes,
		type VolleyBody,
		type VolleyLanes
	} from '$lib/api/client';
	import { battle } from '$lib/battle.svelte';
	import Fight from '$lib/fight/Fight.svelte';
	import Volley from '$lib/fight/Volley.svelte';
	import { aimed, seat, type Deployment } from '$lib/fight/body';
	import { LANES, type Lane } from '$lib/fight/faces';
	import { cropped, formed, measured, seated, type Blocks } from '$lib/fight/field';
	import type { Mode } from '$lib/fight/Settings.svelte';
	import type { Placed } from '$lib/table';

	type Body = FightBody | VolleyBody;

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

	let body = $derived<Body | null>(last ? $state.snapshot(last.body) : null);
	/** The lane the first of the blocks the table resolved between stands in. */
	const first = $derived.by((): Lane | null => {
		if (last?.action === 'fight')
			return seat(last.body, 'attacker') === 'a' ? 'attacker' : 'target';
		return last ? 'attacker' : null;
	});
	const seed = $derived(
		last && first ? seated(last.between, $state.snapshot(battle.placed), first) : null
	);
	let blocks = $derived(seed);
	let lanes = $state<FightLanes | VolleyLanes | null>(null);
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

	/** The deployment fighting or shooting from a lane, and the phase it takes its weapon for. */
	function deployed(sent: Body, lane: Lane): { wanted: Deployment; phase: 'melee' | 'missile' } {
		if ('shooter' in sent) {
			const side = aimed(lane);
			return { wanted: sent[side], phase: side === 'shooter' ? 'missile' : 'melee' };
		}
		return { wanted: sent[seat(sent, lane)], phase: 'melee' };
	}

	/**
	 * Write a body the graph drew back onto the table: each block re-costed as
	 * it is now fielded, standing where the battlefield left it, and the action
	 * resolved again so the table's result is this one.
	 */
	async function commit(sent: Body, at: Blocks | null, ask: number) {
		const open = battle.resolved;
		if (!open || !first) return;
		const client = api(page.url.origin, fetch);
		const next: Placed[] = [];
		for (const lane of LANES) {
			const id = open.between[lane === first ? 0 : 1];
			const standing = battle.placed.find((each) => each.id === id);
			if (!standing) return;
			const { wanted, phase } = deployed(sent, lane);
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
			const where = at?.[lane] ?? standing;
			next.push({
				...standing,
				block,
				[phase]: wanted.weapon ?? '',
				x: where.x,
				y: where.y,
				facing: where.facing
			});
		}
		const placed = () =>
			battle.placed.map((each) => next.find((one) => one.id === each.id) ?? each);
		if ('shooter' in sent) {
			const { data: report } = await client.POST('/volley', { body: sent });
			if (!report || ask !== asked) return;
			battle.placed = placed();
			battle.resolved = { action: 'volley', between: open.between, body: sent, report };
		} else {
			const { data: report } = await client.POST('/fight', { body: sent });
			if (!report || ask !== asked) return;
			battle.placed = placed();
			battle.resolved = { action: 'fight', between: open.between, body: sent, report };
		}
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
		const sent = body;
		if (!sent || !field) return;
		const { full_inches, arc } = measured(field.blocks);
		if ('shooter' in sent) {
			if (sent.distance !== full_inches) body = { ...sent, distance: full_inches };
			return;
		}
		const charge = sent.charge;
		if (charge && (charge.full_inches !== full_inches || charge.arc !== arc))
			body = { ...sent, charge: { ...charge, full_inches, arc } };
	});

	async function drawn(sent: Body) {
		const client = api(page.url.origin, fetch);
		if ('shooter' in sent) return client.POST('/graph/volley', { body: sent });
		return client.POST('/graph/fight', { body: sent });
	}

	$effect(() => {
		const sent = body;
		if (!sent) return;
		const ask = ++asked;
		pending = true;
		const wait = setTimeout(
			async () => {
				const { data, error: refused } = await drawn(sent);
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
					!!last &&
					(JSON.stringify(sent) !== JSON.stringify(last.body) || untrack(() => moved(at)));
				if (untrack(() => mode) === 'edit' && changed) commit(sent, at, ask);
			},
			untrack(() => lanes) ? 250 : 0
		);
		return () => clearTimeout(wait);
	});

	const onmove = (lane: Lane, block: Placed) => blocks && (blocks = { ...blocks, [lane]: block });
</script>

<div class="matchup">
	<a class="btn btn-sm" href={resolve('/table')}>← table</a>
	{#if matchup}<span>{matchup}</span>{/if}
</div>

{#if refusal}<p class="refuse">{refusal}</p>{/if}
{#if body && lanes}
	{#if 'shooter' in body && 'panic' in lanes}
		<Volley
			{lanes}
			{body}
			stale={pending || !!refusal}
			bind:mode
			{field}
			onedit={(next) => (body = next)}
			{onmove}
		/>
	{:else if !('shooter' in body) && 'result' in lanes}
		<Fight
			{lanes}
			{body}
			stale={pending || !!refusal}
			bind:mode
			{field}
			onedit={(next) => (body = next)}
			{onmove}
		/>
	{/if}
{/if}
