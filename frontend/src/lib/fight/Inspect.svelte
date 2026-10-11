<script lang="ts">
	import Spread from '$lib/charts/Spread.svelte';
	import { percent } from '$lib/charts/scale';
	import type { FightBody, FightLanes, LandedRule, StandingAt } from '$lib/api/client';
	import Unit from './Unit.svelte';
	import { redeployed, seat } from './body';
	import { other, type Lane } from './layout';

	interface Props {
		lanes: FightLanes;
		body: FightBody;
		/** The node open in the panel, by the id the drawing gives it. */
		id: string;
		/** Whether a unit's editor is open, rather than only its rules. */
		editing: boolean;
		onedit: (body: FightBody) => void;
		onclose: () => void;
	}

	let { lanes, body, id, editing, onedit, onclose }: Props = $props();

	interface Shown {
		title: string;
		rules: LandedRule[];
		standing: StandingAt | null;
		chances: [string, number][];
	}

	const named = (lane: Lane) => lanes.units[lane].name;

	const shown = $derived.by((): Shown => {
		const [kind, first, second] = id.split(':');
		const bare = { rules: [], standing: null, chances: [] };
		if (kind === 'unit') {
			const lane = first as Lane;
			return { ...bare, title: named(lane), rules: lanes.units[lane].rules };
		}
		if (kind === 'battlefield') return { ...bare, title: 'Battlefield' };
		if (kind === 'charge') return { ...bare, title: 'Charge', rules: lanes.charge?.rules ?? [] };
		if (kind === 'reaction') return { ...bare, title: 'Reaction' };
		if (kind === 'volley') {
			const standing = lanes.standing.attacker.find((each) => each.after === 'volley') ?? null;
			return {
				...bare,
				title: 'Stand & Shoot',
				rules: lanes.volley?.rules ?? [],
				standing
			};
		}
		if (kind === 'strike') {
			const strike = lanes.strikes[Number(first)];
			const lane = strike.side as Lane;
			const standing =
				lanes.standing[other(lane)].find((each) => each.after === strike.slot) ?? null;
			return {
				...bare,
				title: `${strike.label} · ${named(lane)}`,
				rules: strike.rules,
				standing
			};
		}
		if (kind === 'pill') {
			const lane = first as Lane;
			return { ...bare, title: named(lane), standing: lanes.standing[lane][Number(second)] };
		}
		if (kind === 'result') {
			const { result } = lanes;
			return {
				...bare,
				title: 'Combat result',
				rules: result.rules,
				chances: [
					[named('attacker'), result.attacker_wins],
					['draw', result.draw],
					[named('target'), result.target_wins]
				]
			};
		}
		const lane = first as Lane;
		const test = lanes.breaks[lane];
		return {
			...bare,
			title: `Break test · ${named(lane)}`,
			rules: test.rules,
			chances: [
				['Give Ground', test.give_ground],
				['Fall Back in Good Order', test.fall_back_in_good_order],
				['Break', test.break]
			]
		};
	});

	const editable = $derived(id.startsWith('unit:') && editing ? (id.split(':')[1] as Lane) : null);
</script>

<aside class="inspect">
	<header>
		<h3>{shown.title}</h3>
		<button class="btn btn-ghost btn-sm" aria-label="close" onclick={onclose}>×</button>
	</header>

	{#if editable}
		{@const lane = editable}
		{#key lane}
			<Unit
				deployment={body[seat(body, lane)]}
				frontage={lanes.units[lane].frontage}
				onchange={(change) => onedit(redeployed(body, lane, change))}
			/>
		{/key}
	{/if}

	{#if shown.rules.length}
		<h2>rules</h2>
		{#each shown.rules as rule}
			<label class="ruled">
				<input type="checkbox" checked={rule.applied} disabled />
				<span>{rule.name}</span>
				<i class="who {rule.side}" title={named(rule.side as Lane)}></i>
			</label>
		{/each}
	{/if}

	{#if shown.standing}
		<h2>models standing</h2>
		<Spread values={shown.standing.distribution} unit="models" mean={shown.standing.models} />
	{/if}

	{#if shown.chances.length}
		<h2>chances</h2>
		{#each shown.chances as [name, p]}
			<div class="chance">
				<span>{name}</span>
				<b class="num">{percent(p)}</b>
				<i style:width="{p * 100}%"></i>
			</div>
		{/each}
	{/if}
</aside>

<style>
	.inspect {
		display: grid;
		align-content: start;
		gap: var(--space-2);
		padding: var(--space-3);
		overflow: auto;
		background: var(--panel);
		border: 1px solid var(--line);
		box-shadow: 0 2px 12px rgb(0 0 0 / 0.12);
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--line);
	}
	header h3 {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	h2 {
		margin-top: var(--space-2);
	}
	.ruled {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.ruled span {
		flex: 1;
	}
	.who {
		width: 0.6rem;
		height: 0.6rem;
	}
	.who.attacker {
		background: var(--series-1);
	}
	.who.target {
		background: var(--series-2);
	}
	.chance {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 0.1rem var(--space-2);
		font-size: var(--text-sm);
	}
	.chance i {
		grid-column: 1 / -1;
		height: 0.5rem;
		background: var(--series-1);
	}
</style>
