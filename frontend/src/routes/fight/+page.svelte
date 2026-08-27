<script lang="ts">
	import Side from '$lib/Side.svelte';
	import { api, type FightReport, type FightSide, type MusteredUnit } from '$lib/api/client';

	const ROSTER_KEY = 'avelorn:list';
	const ARCS = ['front', 'flank', 'rear'] as const;

	let { data } = $props();

	let roster = $state<MusteredUnit[]>([]);
	let a = $state<MusteredUnit | null>(null);
	let b = $state<MusteredUnit | null>(null);
	let aWeapon = $state('');
	let bWeapon = $state('');
	let charger = $state<'' | 'a' | 'b'>('');
	let inches = $state(8);
	let arc = $state<(typeof ARCS)[number]>('front');
	let report = $state<FightReport | null>(null);
	let refusal = $state('');
	let resolving = $state(false);
	// A side mid-remuster is not the side the fight would resolve against.
	let mustering = $state(0);

	$effect(() => {
		const saved = localStorage.getItem(ROSTER_KEY);
		if (saved) roster = JSON.parse(saved);
	});

	const ready = $derived(a !== null && b !== null && mustering === 0);

	async function resolveFight() {
		if (!a || !b) return;
		refusal = '';
		resolving = true;
		const { data: fought, error: refused } = await api(window.location.origin, fetch).POST(
			'/fight',
			{
				body: {
					a: { unit: a.unit, size: a.size, options: a.options, weapon: aWeapon },
					b: { unit: b.unit, size: b.size, options: b.options, weapon: bWeapon },
					charge: charger ? { side: charger, full_inches: inches, arc } : null
				}
			}
		);
		resolving = false;
		if (!fought) {
			report = null;
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not resolve that';
			return;
		}
		report = fought;
	}

	const pct = (p: number) => `${(p * 100).toFixed(1)}%`;

	// The tail of a casualty distribution is mostly zeroes; show what can
	// actually happen rather than every index up to the unit's size.
	function plausible(side: FightSide) {
		return side.casualties
			.map((probability, removed) => ({ removed, probability }))
			.filter((row) => row.probability >= 0.0005);
	}
</script>

<h1>Fight</h1>
<p class="meta">
	One round of close combat, resolved exactly: both sides strike in Initiative order, the Wounds
	tally into a combat result, and the loser takes its Break test.
</p>

<div class="sides">
	<Side
		label="Side A"
		units={data.units}
		{roster}
		block={a}
		onblock={(block) => ((a = block), (report = null))}
		weapon={aWeapon}
		onweapon={(name) => ((aWeapon = name), (report = null))}
		onbusy={(busy) => (mustering += busy ? 1 : -1)}
	/>
	<Side
		label="Side B"
		units={data.units}
		{roster}
		block={b}
		onblock={(block) => ((b = block), (report = null))}
		weapon={bWeapon}
		onweapon={(name) => ((bWeapon = name), (report = null))}
		onbusy={(busy) => (mustering += busy ? 1 : -1)}
	/>
</div>

<fieldset class="charge">
	<legend>Charge</legend>
	<label>
		Delivered by
		<select bind:value={charger}>
			<option value="">nobody — both stood</option>
			<option value="a">Side A</option>
			<option value="b">Side B</option>
		</select>
	</label>
	{#if charger}
		<label>
			Full inches moved
			<input type="number" min="0" bind:value={inches} />
		</label>
		<label>
			Into the
			<select bind:value={arc}>
				{#each ARCS as name}
					<option value={name}>{name}</option>
				{/each}
			</select>
		</label>
	{/if}
</fieldset>

<button disabled={!ready || resolving} onclick={resolveFight}>
	{resolving ? 'Resolving…' : 'Fight'}
</button>
{#if mustering > 0}
	<span class="meta">deploying…</span>
{:else if !ready}
	<span class="meta">pick both sides first</span>
{/if}
{#if refusal}<p class="refusal">{refusal}</p>{/if}

{#if report}
	{@const sides = [
		{ key: 'A', side: report.a, wins: report.p_a_wins },
		{ key: 'B', side: report.b, wins: report.p_b_wins }
	]}

	<h2>{report.a.name} vs {report.b.name}</h2>

	<table class="verdict">
		<thead>
			<tr><th>A wins</th><th>Draw</th><th>B wins</th></tr>
		</thead>
		<tbody>
			<tr>
				<td>{pct(report.p_a_wins)}</td>
				<td>{pct(report.p_draw)}</td>
				<td>{pct(report.p_b_wins)}</td>
			</tr>
		</tbody>
	</table>

	<p class="meta">
		{#if report.first_striker}
			Side {report.first_striker.toUpperCase()} strikes first, on an effective Initiative of
			{report.first_striker === 'a' ? report.a.initiative : report.b.initiative}.
		{:else}
			Equal Initiative — the blows land simultaneously.
		{/if}
	</p>

	<div class="sides">
		{#each sides as { key, side, wins }}
			<section>
				<h3>Side {key} — {side.name} × {side.size}</h3>
				<p class="meta">
					{side.weapon} · Initiative {side.initiative} · rank bonus +{side.rank_bonus} · unit strength
					{side.unit_strength}
				</p>
				<p>Loses <strong>{side.expected_casualties.toFixed(2)}</strong> models on average.</p>

				<table>
					<thead>
						<tr><th>Models lost</th><th>Chance</th></tr>
					</thead>
					<tbody>
						{#each plausible(side) as row}
							<tr><td>{row.removed}</td><td>{pct(row.probability)}</td></tr>
						{/each}
					</tbody>
				</table>

				<h4>If it loses the round</h4>
				<p class="meta">Wins {pct(wins)} of the time; the rest is below.</p>
				<table>
					<tbody>
						<tr><td>Gives ground</td><td>{pct(side.gives_ground)}</td></tr>
						<tr><td>Falls back in good order</td><td>{pct(side.falls_back)}</td></tr>
						<tr><td>Breaks and flees</td><td>{pct(side.breaks)}</td></tr>
					</tbody>
				</table>
			</section>
		{/each}
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

	fieldset.charge {
		border: 1px solid var(--line);
		border-radius: 3px;
		padding: 1rem;
		margin-bottom: 1rem;
	}

	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	select,
	input[type='number'] {
		font: inherit;
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

	table.verdict {
		width: auto;
		margin: 1rem 0 0.5rem;

		td {
			font-size: 1.2rem;
		}
	}

	h3 {
		font-size: 1rem;
		margin-bottom: 0.2rem;
	}

	h4 {
		font-size: 0.9rem;
		margin: 1.2rem 0 0.2rem;
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
