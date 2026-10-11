<script lang="ts">
	import type { FightBody, FightLanes } from '$lib/api/client';
	import type { Placed as Block } from '$lib/table';
	import Lanes from './Lanes.svelte';
	import Unit from './Unit.svelte';
	import { redeployed, seat } from './body';
	import type { Field } from './field';
	import type { Lane } from './layout';
	import { VIEWS, type View } from './odds';

	interface Props {
		lanes: FightLanes;
		body: FightBody;
		/** Whether the drawing is older than the body: a redraw on its way, or the body refused. */
		stale: boolean;
		/** The blocks the table placed, which the battlefield measures; null with no table. */
		field: Field | null;
		onedit: (body: FightBody) => void;
		/** A block dragged across the battlefield's crop. */
		onmove: (lane: Lane, block: Block) => void;
	}

	let { lanes, body, stale, field, onedit, onmove }: Props = $props();

	let open = $state<string | null>(null);
	let editing = $state<Lane | null>(null);
	let view = $state<View>('conditional');

	function toggle(id: string) {
		editing = null;
		open = open === id ? null : id;
	}

	function close() {
		editing = null;
		open = null;
	}
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && close()} />

<div class="fight" class:stale>
	<div class="views" role="radiogroup" aria-label="chances">
		{#each VIEWS as each}
			<button
				role="radio"
				aria-checked={view === each}
				class:on={view === each}
				onclick={() => (view = each)}>{each}</button
			>
		{/each}
	</div>
	<div class="stage">
		<Lanes
			{lanes}
			{view}
			charge={body.charge ?? null}
			{field}
			{onmove}
			{open}
			{editing}
			ontoggle={toggle}
			onedit={(lane) => {
				open = `unit:${lane}`;
				editing = lane;
			}}
			oncharge={(change) =>
				body.charge && onedit({ ...body, charge: { ...body.charge, ...change } })}
		>
			{#snippet editor(lane)}
				{#key lane}
					<Unit
						deployment={body[seat(body, lane)]}
						frontage={lanes.units[lane].frontage}
						onchange={(change) => onedit(redeployed(body, lane, change))}
					/>
				{/key}
			{/snippet}
		</Lanes>
	</div>
</div>

<style>
	.fight {
		position: relative;
		min-height: 24rem;
		border: 1px solid var(--line);
	}
	.views {
		position: absolute;
		top: 4px;
		right: 4px;
		display: flex;
		gap: 2px;
	}
	.views button {
		height: 22px;
		padding: 0 0.6rem;
		font-size: 12px;
		cursor: pointer;
	}
	.views button.on {
		color: var(--on-accent);
		background: var(--accent);
		border-color: var(--accent);
	}
	.stage {
		overflow-x: auto;
	}
	.fight.stale .stage {
		opacity: 0.7;
		transition: opacity 0.2s 0.15s;
	}
</style>
