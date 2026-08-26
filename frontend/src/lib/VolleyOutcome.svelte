<script lang="ts">
	import type { VolleyReport } from '$lib/api/client';

	interface Props {
		report: VolleyReport;
	}

	let { report }: Props = $props();

	const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
	const plus = (n: number | null) => (n === null ? '—' : `${n}+`);

	// The tail is mostly zeroes; show what can actually happen.
	const plausible = (rows: number[]) =>
		rows
			.map((probability, count) => ({ count, probability }))
			.filter((r) => r.probability >= 0.0005);
</script>

<h2>{report.shooter.name} shoot {report.target.name}</h2>
<p class="meta">
	{report.shots} shots with the {report.shooter.weapon} · hits on {plus(report.hit_target)} · wounds on
	{plus(report.wound_target)} · armour save {plus(report.save_target)} · ward {plus(
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
