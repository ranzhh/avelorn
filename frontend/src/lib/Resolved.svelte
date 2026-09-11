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

	const plus = (n: number | null) => (n === null ? '—' : `${n}+`);
	// Printed sign convention: a penalty is negative, and it raises the target.
	const signed = (n: number) => (n < 0 ? `${n}` : `+${n}`);

	// The To Hit target opens to the ledger behind it; the wound and save
	// targets are single chart lookups, so they wear their operands inline.
	let ledger = $state(false);
</script>

{#if fight}
	<Outcomes
		scheme="poles"
		segments={[
			{ label: fight.a.name, value: fight.p_a_wins },
			{ label: 'draw', value: fight.p_draw },
			{ label: fight.b.name, value: fight.p_b_wins }
		]}
	/>

	<table class="grid">
		<thead>
			<tr>
				<th></th>
				<th class="num">{fight.a.name}</th>
				<th class="num">{fight.b.name}</th>
			</tr>
		</thead>
		<tbody>
			<tr><td>models</td><td class="num">{fight.a.size}</td><td class="num">{fight.b.size}</td></tr>
			<tr
				><td>weapon</td><td class="num">{fight.a.weapon}</td><td class="num">{fight.b.weapon}</td
				></tr
			>
			<tr>
				<td>initiative</td>
				<td class="num">{fight.a.initiative}</td>
				<td class="num">{fight.b.initiative}</td>
			</tr>
			<tr>
				<td>rank bonus</td>
				<td class="num">+{fight.a.rank_bonus}</td>
				<td class="num">+{fight.b.rank_bonus}</td>
			</tr>
			<tr>
				<td>unit strength</td>
				<td class="num">{fight.a.unit_strength}</td>
				<td class="num">{fight.b.unit_strength}</td>
			</tr>
			<tr>
				<td>losses, mean</td>
				<td class="num neg">{fight.a.expected_casualties.toFixed(2)}</td>
				<td class="num neg">{fight.b.expected_casualties.toFixed(2)}</td>
			</tr>
		</tbody>
	</table>

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

	{#if fight.first_striker}
		<p class="note">first strike {fight.first_striker}</p>
	{/if}
{/if}

{#if volley}
	<table class="grid">
		<tbody>
			<tr><td>shots</td><td class="num">{volley.shots}</td></tr>
			<tr class="opens" class:shown={ledger}>
				<td>
					<button class="open" aria-expanded={ledger} onclick={() => (ledger = !ledger)}>
						to hit
					</button>
				</td>
				<td class="num">{plus(volley.hit_target)}</td>
			</tr>
			{#if ledger}
				<tr class="step">
					<td>{volley.hit_from.basis}</td>
					<td class="num">{plus(volley.hit_from.base)}</td>
				</tr>
				{#each volley.hit_from.steps as step}
					<tr class="step">
						<td>
							<span class="by num" class:neg={step.modifier < 0} class:pos={step.modifier > 0}>
								{signed(step.modifier)}
							</span>
							{step.source ?? 'unattributed'}
						</td>
						<td class="num">{plus(step.target)}</td>
					</tr>
				{/each}
			{/if}
			<tr>
				<td>to wound <span class="from">S {volley.strength} vs T {volley.toughness}</span></td>
				<td class="num">{plus(volley.wound_target)}</td>
			</tr>
			<tr>
				<td>
					armour save
					{#if volley.armour_value !== null}
						<span class="from">
							AV {volley.armour_value}{volley.armour_piercing
								? `, AP ${-volley.armour_piercing}`
								: ''}
						</span>
					{/if}
				</td>
				<td class="num">{plus(volley.save_target)}</td>
			</tr>
			<tr><td>ward</td><td class="num">{plus(volley.ward_target)}</td></tr>
			<tr><td>unsaved per shot</td><td class="num">{volley.p_unsaved.toFixed(4)}</td></tr>
			<tr><td>wounds, mean</td><td class="num">{volley.expected_wounds.toFixed(2)}</td></tr>
			<tr>
				<td>felled, mean</td>
				<td class="num neg">{volley.expected_casualties.toFixed(2)}</td>
			</tr>
		</tbody>
	</table>

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

{#if fight?.not_modelled.length || volley?.not_modelled.length}
	{@const notes = [...new Set([...(fight?.not_modelled ?? []), ...(volley?.not_modelled ?? [])])]}
	<details>
		<summary>{notes.length} unmodelled</summary>
		<ul>
			{#each notes as note}
				<li>{note}</li>
			{/each}
		</ul>
	</details>
{/if}

<style>
	h3 {
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--dim);
	}

	.grid {
		margin: var(--space-2) 0;
	}

	.grid td:first-child {
		color: var(--dim);
	}

	.open {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		padding: 0;
		font: inherit;
		color: var(--dim);
		background: none;
		border: none;
		cursor: pointer;
	}

	.open::before {
		content: '';
		width: 0;
		height: 0;
		border-left: 4px solid var(--faint);
		border-top: 3px solid transparent;
		border-bottom: 3px solid transparent;
		transition: transform var(--transition);
	}

	.opens.shown .open::before {
		transform: rotate(90deg);
	}

	.open:hover {
		color: var(--ink);
	}

	/* The ledger's own rows: subordinate to the target they add up to. */
	.step td {
		border-bottom: none;
		padding-top: 0;
		padding-bottom: 0;
		font-size: var(--text-xs);
		color: var(--faint);
	}

	.step td:first-child {
		padding-left: var(--space-5);
	}

	.by {
		display: inline-block;
		min-width: 1.6rem;
	}

	.from {
		margin-left: var(--space-2);
		font: var(--text-xs) / 1 var(--font-mono);
		color: var(--faint);
	}

	.note {
		margin-top: var(--space-1);
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}

	details {
		margin-top: var(--space-3);
	}

	summary {
		cursor: pointer;
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}

	ul {
		margin: var(--space-1) 0 0;
		padding-left: var(--space-4);
	}

	li {
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}
</style>
