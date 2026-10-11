<script lang="ts">
	import { page } from '$app/state';
	import { api, type FightBody, type FightLanes, type VolleyBody } from '$lib/api/client';
	import { battle } from '$lib/battle.svelte';
	import Fight from '$lib/fight/Fight.svelte';
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

	/** Ask for the lanes of the table's last fight, posting the body it sent. */
	async function fight(body: FightBody): Promise<FightLanes> {
		const { data: lanes, error: refused } = await api(page.url.origin, fetch).POST('/graph/fight', {
			body
		});
		if (!lanes) {
			throw new Error(typeof refused?.detail === 'string' ? refused.detail : 'could not draw that');
		}
		return lanes;
	}

	const last = $derived(battle.resolved);
	const program = $derived(last?.action === 'volley' ? volley(last.body) : null);
	const fought = $derived(last?.action === 'fight' ? fight(last.body) : null);
</script>

{#if fought}
	{#await fought then lanes}
		<Fight {lanes} />
	{:catch refused}
		<p class="refuse">{refused.message}</p>
	{/await}
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
