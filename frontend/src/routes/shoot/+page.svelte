<script lang="ts">
	import Side from '$lib/Side.svelte';
	import { api, type MusteredUnit, type VolleyReport } from '$lib/api/client';

	const ROSTER_KEY = 'avelorn:list';

	let { data } = $props();

	let roster = $state<MusteredUnit[]>([]);
	let shooter = $state<MusteredUnit | null>(null);
	let target = $state<MusteredUnit | null>(null);
	let weapon = $state('');
	let known = $state(true);
	let distance = $state(12);
	let hitModifier = $state(0);
	let report = $state<VolleyReport | null>(null);
	let refusal = $state('');
	let mustering = $state(0);
	let resolving = $state(false);

	$effect(() => {
		const saved = localStorage.getItem(ROSTER_KEY);
		if (saved) roster = JSON.parse(saved);
	});

	const ready = $derived(shooter !== null && target !== null && mustering === 0);

	async function loose() {
		if (!shooter || !target) return;
		refusal = '';
		resolving = true;
		const { data: fired, error: refused } = await api(window.location.origin, fetch).POST(
			'/volley',
			{
				body: {
					shooter: {
						unit: shooter.unit,
						size: shooter.size,
						options: shooter.options,
						weapon: weapon || null
					},
					target: { unit: target.unit, size: target.size, options: target.options },
					distance: known ? distance : null,
					hit_modifier: hitModifier
				}
			}
		);
		resolving = false;
		if (!fired) {
			report = null;
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		report = fired;
	}

	const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
	const plus = (n: number | null) => (n === null ? '—' : `${n}+`);

	// The tail is mostly zeroes; show what can actually happen.
	const plausible = (rows: number[]) =>
		rows
			.map((probability, count) => ({ count, probability }))
			.filter((r) => r.probability >= 0.0005);
</script>

<h1>Shoot</h1>
<p class="meta">
	One volley, resolved exactly, and the panic its casualties cause. The to-hit target reported is
	the one the volley used, range and movement already folded in.
</p>

<div class="sides">
	<Side
		label="Shooter"
		units={data.units}
		{roster}
		block={shooter}
		onblock={(block) => ((shooter = block), (report = null))}
		{weapon}
		onweapon={(name) => ((weapon = name), (report = null))}
		onbusy={(busy) => (mustering += busy ? 1 : -1)}
		wields="missile"
	/>
	<Side
		label="Target"
		units={data.units}
		{roster}
		block={target}
		onblock={(block) => ((target = block), (report = null))}
		weapon=""
		onweapon={() => {}}
		onbusy={(busy) => (mustering += busy ? 1 : -1)}
		arms={false}
	/>
</div>

<fieldset class="range">
	<legend>The shot</legend>
	<label>
		<input type="checkbox" bind:checked={known} />
		The distance is known
	</label>
	{#if known}
		<label>
			Inches to the target
			<input type="number" min="0" bind:value={distance} />
		</label>
	{:else}
		<p class="meta">
			The long-range modifier cannot be settled without a distance, so it is left unapplied and
			reported rather than guessed.
		</p>
	{/if}
	<label>
		To-hit modifier
		<input type="number" bind:value={hitModifier} />
		<span class="meta">cover, a large target, a unit that moved — what the corpus cannot know</span>
	</label>
</fieldset>

<button disabled={!ready || resolving} onclick={loose}>
	{resolving ? 'Resolving…' : 'Loose'}
</button>
{#if mustering > 0}
	<span class="meta">deploying…</span>
{:else if !ready}
	<span class="meta">pick a shooter and a target first</span>
{/if}
{#if refusal}<p class="refusal">{refusal}</p>{/if}

{#if report}
	<h2>{report.shooter.name} shoot {report.target.name}</h2>
	<p class="meta">
		{report.shots} shots with the {report.shooter.weapon} · hits on {plus(report.hit_target)} · wounds
		on {plus(report.wound_target)} · armour save {plus(report.save_target)} · ward {plus(
			report.ward_target
		)}
	</p>

	<p>
		Fells <strong>{report.expected_casualties.toFixed(2)}</strong> models on average, out of
		{report.target.size}.
	</p>

	<div class="sides">
		<section>
			<h3>Models felled</h3>
			<table>
				<thead>
					<tr><th>Removed</th><th>Chance</th></tr>
				</thead>
				<tbody>
					{#each plausible(report.casualties) as row}
						<tr><td>{row.count}</td><td>{pct(row.probability)}</td></tr>
					{/each}
				</tbody>
			</table>
		</section>

		<section>
			<h3>What its nerve does</h3>
			<p class="meta">Forced to test {pct(report.panic.tests)} of the time.</p>
			<table>
				<tbody>
					<tr><td>Holds</td><td>{pct(report.panic.holds)}</td></tr>
					<tr><td>Falls back</td><td>{pct(report.panic.falls_back)}</td></tr>
					<tr><td>Flees</td><td>{pct(report.panic.flees)}</td></tr>
					<tr><td>Wiped out</td><td>{pct(report.panic.destroyed)}</td></tr>
				</tbody>
			</table>
			{#if report.panic.reroll_from}
				<p class="meta">A failed test is re-rolled by {report.panic.reroll_from}.</p>
			{/if}
		</section>
	</div>

	{#if report.not_modelled.length}
		<details>
			<summary>{report.not_modelled.length} things the engine held without applying</summary>
			<ul>
				{#each report.not_modelled as note}
					<li>{note}</li>
				{/each}
			</ul>
		</details>
	{/if}
{/if}

<style>
	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	fieldset.range {
		border: 1px solid var(--line);
		border-radius: 3px;
		padding: 1rem;
		margin-bottom: 1rem;
	}

	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	input[type='number'] {
		font: inherit;
		width: 5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--line);
		border-radius: 3px;
		background: var(--sunken);
	}

	button {
		font: inherit;
		padding: 0.4rem 1rem;
		border: 1px solid var(--line);
		border-radius: 3px;
		background: var(--sunken);
		cursor: pointer;
	}

	button:disabled {
		color: var(--dim);
		cursor: not-allowed;
	}

	h3 {
		font-size: 1rem;
		margin-bottom: 0.4rem;
	}

	details {
		margin-top: 1.5rem;
		font-size: 0.9rem;

		summary {
			cursor: pointer;
			color: var(--dim);
		}
	}

	.meta {
		color: var(--dim);
		font-size: 0.85rem;
	}

	.refusal {
		color: var(--neg);
		font-size: 0.9rem;
	}
</style>
