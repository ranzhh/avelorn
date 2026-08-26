<script lang="ts">
	import type { FightReport, FightSide } from '$lib/api/client';

	interface Props {
		report: FightReport;
	}

	let { report }: Props = $props();

	const pct = (p: number) => `${(p * 100).toFixed(1)}%`;

	// The tail of a casualty distribution is mostly zeroes; show what can
	// actually happen rather than every index up to the unit's size.
	function plausible(side: FightSide) {
		return side.casualties
			.map((probability, removed) => ({ removed, probability }))
			.filter((row) => row.probability >= 0.0005);
	}

	const sides = $derived([
		{ key: 'A', side: report.a, wins: report.p_a_wins },
		{ key: 'B', side: report.b, wins: report.p_b_wins }
	]);
</script>

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

<style>
	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}

	h2 {
		font-size: 1.1rem;
	}

	h3 {
		font-size: 1rem;
		margin-bottom: 0.4rem;
	}

	h4 {
		font-size: 0.9rem;
		margin-bottom: 0.2rem;
	}

	details {
		margin-top: 1rem;
		font-size: 0.9rem;

		summary {
			cursor: pointer;
			color: var(--muted);
		}
	}

	.meta {
		color: var(--muted);
		font-size: 0.85rem;
	}
</style>
