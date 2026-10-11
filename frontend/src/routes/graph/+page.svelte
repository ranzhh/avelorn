<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { api, type FightBody, type FightLanes, type VolleyBody } from '$lib/api/client';
	import { battle } from '$lib/battle.svelte';
	import Fight from '$lib/fight/Fight.svelte';
	import { cropped, formed, measured, seated } from '$lib/fight/field';
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
	const program = $derived(last?.action === 'volley' ? volley(last.body) : null);

	let body = $derived<FightBody | null>(
		last?.action === 'fight' ? $state.snapshot(last.body) : null
	);
	const blocks = $derived(
		last?.action === 'fight'
			? seated(last.body, last.between, $state.snapshot(battle.placed))
			: null
	);
	let lanes = $state<FightLanes | null>(null);
	let refusal = $state('');
	let pending = $state(false);
	let asked = 0;

	const field = $derived(
		blocks &&
			lanes && {
				blocks: {
					attacker: formed(blocks.attacker, lanes.units.attacker),
					target: formed(blocks.target, lanes.units.target)
				},
				crop: cropped(blocks)
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
				if (data) lanes = data;
			},
			untrack(() => lanes) ? 250 : 0
		);
		return () => clearTimeout(wait);
	});
</script>

{#if last?.action === 'fight' && body}
	{#if refusal}<p class="refuse">{refusal}</p>{/if}
	{#if lanes}
		<Fight {lanes} {body} stale={pending || !!refusal} {field} onedit={(next) => (body = next)} />
	{/if}
{:else if last?.action === 'volley' && program}
	<p class="meta">
		{last.report.shooter.name} ×{last.report.shooter.size} shoot
		{last.report.target.name} ×{last.report.target.size} at {last.body.distance}in
	</p>
	{#await program}
		<p class="meta">drawing…</p>
	{:then program}
		<Graph {program} />
	{:catch refused}
		<p class="refuse">{refused.message}</p>
	{/await}
{/if}
