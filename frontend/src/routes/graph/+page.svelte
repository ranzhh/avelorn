<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { api } from '$lib/api/client';
	import { battle, type Resolution } from '$lib/battle.svelte';
	import Graph from '$lib/graph/Graph.svelte';
	import type { Program } from '$lib/graph/types';

	/** Ask for the program the table's last volley ran on, posting the body it sent. */
	async function draw(last: Resolution): Promise<Program | null> {
		if (last.action === 'fight') return null;
		const { data: program, error: refused } = await api(page.url.origin, fetch).POST(
			'/graph/volley',
			{ body: last.body }
		);
		if (!program) {
			throw new Error(typeof refused?.detail === 'string' ? refused.detail : 'could not draw that');
		}
		return program as unknown as Program;
	}

	const last = $derived(battle.resolved);
	const drawing = $derived(last && draw(last));
</script>

{#if last && drawing}
	<p class="meta">
		{#if last.action === 'fight'}
			{last.report.a.name} ×{last.report.a.size}
			{last.body.charge ? 'charge' : 'fight'}
			{last.report.b.name} ×{last.report.b.size}
			{last.body.charge ? `from ${last.body.charge.full_inches}in` : ''}
		{:else}
			{last.report.shooter.name} ×{last.report.shooter.size} shoot
			{last.report.target.name} ×{last.report.target.size} at {last.body.distance}in
		{/if}
	</p>
	{#await drawing}
		<p class="meta">drawing…</p>
	{:then program}
		{#if program}<Graph {program} />{/if}
	{:catch refused}
		<p class="refuse">{refused.message}</p>
	{/await}
{:else}
	<p class="meta">
		Nothing resolved yet: charge or shoot on the <a href={resolve('/table')}>table</a>.
	</p>
{/if}
