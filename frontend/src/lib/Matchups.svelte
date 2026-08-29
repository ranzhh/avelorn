<script lang="ts">
	import { percent } from '$lib/charts/scale';
	import { FULL_CHARGE, pairings, ranked, roster, shade, type Stance } from '$lib/matchups';
	import { api, type FightReport } from '$lib/api/client';
	import type { Placed } from '$lib/table';

	interface Props {
		placed: Placed[];
		/** Show one pairing in full, in the dock that reads a single round. */
		onread: (report: FightReport) => void;
	}

	let { placed, onread }: Props = $props();

	let stance = $state<Stance>('engaged');
	// Row-major, indexed the way `placed` is: won[row][column] is the chance the
	// row's block wins that round. null where the pairing has not resolved.
	let won = $state<(number | null)[][]>([]);
	let reports: Record<string, FightReport> = {};
	let resolving = $state(false);
	let refusals = $state(0);
	// The roster the grid on screen was resolved for. Anything else is stale.
	let shown = $state('');

	const wanted = $derived(roster(placed, stance));
	const stale = $derived(placed.length > 1 && wanted !== shown);
	const fights = $derived(pairings(placed.length).length);

	function deployment(block: Placed) {
		return {
			unit: block.block.unit,
			size: block.block.size,
			options: block.block.options,
			weapon: block.melee || null,
			frontage: block.block.footprint?.files ?? null
		};
	}

	async function resolve() {
		const roll = placed;
		const key = roster(roll, stance);
		resolving = true;
		refusals = 0;
		const grid: (number | null)[][] = roll.map(() => roll.map(() => null));
		const fresh: Record<string, FightReport> = {};
		const client = api(window.location.origin, fetch);
		await Promise.all(
			pairings(roll.length).map(async ({ row, column }) => {
				const { data: report } = await client.POST('/fight', {
					body: {
						a: deployment(roll[row]),
						b: deployment(roll[column]),
						charge:
							stance === 'charged' ? { side: 'a', full_inches: FULL_CHARGE, arc: 'front' } : null
					}
				});
				if (!report) {
					refusals += 1;
					return;
				}
				grid[row][column] = report.p_a_wins;
				fresh[`${row}:${column}`] = report;
			})
		);
		won = grid;
		reports = fresh;
		shown = key;
		resolving = false;
	}

	function open(row: number, column: number) {
		const report = reports[`${row}:${column}`];
		if (report) onread(report);
	}

	const best = $derived(
		won.map((row, index) => {
			const order = ranked(row);
			return { index, top: order[0] ?? null, worst: order[order.length - 1] ?? null };
		})
	);
</script>

<div class="head">
	<div class="cluster">
		<label class="field">
			<span>stance</span>
			<select class="select" bind:value={stance}>
				<option value="engaged">already engaged</option>
				<option value="charged">row charges the front</option>
			</select>
		</label>
		<span class="meta num">{fights} fights</span>
	</div>
	<button
		class="btn btn-sm"
		class:btn-primary={stale}
		disabled={resolving || fights === 0}
		onclick={resolve}
	>
		{resolving ? 'resolving…' : stale ? 'resolve' : 'again'}
	</button>
</div>

{#if placed.length < 2}
	<p class="meta">two blocks on the table make a matchup</p>
{:else if won.length !== placed.length}
	<p class="meta">unresolved</p>
{:else}
	<table class="matrix" class:stale>
		<thead>
			<tr>
				<th class="corner">row wins</th>
				{#each placed as against (against.id)}
					<th class="num against" title={against.block.name}>{against.mark}</th>
				{/each}
				<th class="reads">best</th>
				<th class="reads">worst</th>
			</tr>
		</thead>
		<tbody>
			{#each placed as block, row (block.id)}
				<tr>
					<th class="who"><span class="mark">{block.mark}</span>{block.block.name}</th>
					{#each placed as against, column (against.id)}
						{@const p = won[row][column]}
						<td class="cell">
							{#if row === column}
								<span class="self">·</span>
							{:else if p === null}
								<span class="self">—</span>
							{:else}
								<button
									class="num p"
									style="background: {shade(p)}"
									title="{block.block.name} vs {against.block.name}"
									onclick={() => open(row, column)}
								>
									{percent(p)}
								</button>
							{/if}
						</td>
					{/each}
					<td class="num reads">
						{best[row]?.top ? placed[best[row].top.column].mark : '—'}
					</td>
					<td class="num reads">
						{best[row]?.worst ? placed[best[row].worst.column].mark : '—'}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
	{#if refusals}
		<p class="refuse">{refusals} of {fights} refused</p>
	{/if}
{/if}

<style>
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		margin-bottom: var(--space-2);
	}

	.head .field {
		gap: var(--space-2);
	}

	.matrix {
		width: auto;
	}

	/* The answers on screen were resolved for a roster that has since changed. */
	.matrix.stale {
		opacity: 0.45;
	}

	.matrix th,
	.matrix td {
		border-bottom: none;
		padding: 1px;
	}

	.corner,
	.who {
		text-align: left;
		font: var(--text-sm) / 1.6 var(--font-sans);
		font-weight: 400;
		color: var(--dim);
		padding-right: var(--space-3);
		background: none;
	}

	.corner {
		position: static;
		font: 600 var(--text-xs) / 1 var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	/* A row header is a label, not a column heading: the global th rule
	   uppercases and sticks those, and neither suits a unit's name. */
	.who {
		position: static;
		color: var(--ink);
		text-transform: none;
		white-space: nowrap;
	}

	.mark {
		display: inline-block;
		min-width: 1.2rem;
		font-family: var(--font-mono);
		color: var(--dim);
	}

	.against {
		position: static;
		width: 3.4rem;
		text-align: center;
		font-family: var(--font-mono);
		background: none;
	}

	.cell {
		padding: 1px;
	}

	.p {
		display: block;
		width: 100%;
		padding: 2px var(--space-2);
		font: var(--text-sm) / 1.5 var(--font-mono);
		font-variant-numeric: tabular-nums;
		color: var(--ink);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		cursor: pointer;
		text-align: right;
	}

	.p:hover {
		border-color: var(--ink);
	}

	.self {
		display: block;
		text-align: center;
		color: var(--faint);
	}

	.reads {
		position: static;
		padding-left: var(--space-4);
		font-family: var(--font-mono);
		color: var(--dim);
		background: none;
	}

	th.reads {
		font: 600 var(--text-xs) / 1 var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		text-align: right;
	}
</style>
