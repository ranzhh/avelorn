<script lang="ts">
	import Outcomes from '$lib/charts/Outcomes.svelte';
	import Spread from '$lib/charts/Spread.svelte';
	import { percent } from '$lib/charts/scale';
	import type { FightReport, VolleyReport } from '$lib/api/client';

	interface Props {
		fight?: FightReport | null;
		volley?: VolleyReport | null;
	}

	let { fight = null, volley = null }: Props = $props();
</script>

{#if fight}
	{#each [fight.a, fight.b] as side}
		<h3>{side.name} losses</h3>
		<Spread values={side.casualties} unit="models lost" mean={side.expected_casualties} />
		<h3>if {side.name} lose the round</h3>
		<Outcomes
			segments={[
				{ label: 'gives ground', value: side.gives_ground },
				{ label: 'falls back', value: side.falls_back },
				{ label: 'breaks', value: side.breaks }
			]}
		/>
	{/each}
{/if}

{#if volley}
	<h3>{volley.target.name} felled</h3>
	<Spread values={volley.casualties} unit="models felled" mean={volley.expected_casualties} />

	<h3>{volley.target.name} nerve</h3>
	<Outcomes
		segments={[
			{ label: 'holds', value: volley.panic.holds },
			{ label: 'falls back', value: volley.panic.falls_back },
			{ label: 'flees', value: volley.panic.flees },
			{ label: 'wiped out', value: volley.panic.destroyed }
		]}
	/>
	<p class="note">forced to test {percent(volley.panic.tests)}</p>
	{#if volley.panic.reroll_from}
		<p class="note">re-roll from {volley.panic.reroll_from}</p>
	{/if}
{/if}
