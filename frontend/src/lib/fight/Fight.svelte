<script lang="ts">
	import type { FightBody, FightLanes } from '$lib/api/client';
	import Inspect from './Inspect.svelte';
	import Lanes from './Lanes.svelte';

	interface Props {
		lanes: FightLanes;
		body: FightBody;
		/** Whether the drawing is older than the body: a redraw on its way, or the body refused. */
		stale: boolean;
		onedit: (body: FightBody) => void;
	}

	let { lanes, body, stale, onedit }: Props = $props();

	let selected = $state<string | null>(null);
	let editing = $state(false);
	let side = $state<'left' | 'right'>('right');

	function select(id: string | null, away: 'left' | 'right' = side) {
		if (id !== selected) editing = false;
		selected = id;
		side = away;
	}
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && select(null)} />

<div class="fight" class:stale>
	<div class="stage">
		<Lanes
			{lanes}
			charge={body.charge ?? null}
			{selected}
			onselect={select}
			onopen={(lane) => {
				select(`unit:${lane}`, 'right');
				editing = true;
			}}
			oncharge={(change) =>
				body.charge && onedit({ ...body, charge: { ...body.charge, ...change } })}
		/>
	</div>
	{#if selected}
		<div class="drawer" class:flipped={side === 'left'}>
			<Inspect {lanes} {body} id={selected} {editing} {onedit} onclose={() => select(null)} />
		</div>
	{/if}
</div>

<style>
	.fight {
		position: relative;
		min-height: 24rem;
		border: 1px solid var(--line);
	}
	.stage {
		overflow-x: auto;
	}
	.fight.stale .stage {
		opacity: 0.7;
		transition: opacity 0.2s 0.15s;
	}
	.drawer {
		position: absolute;
		top: 0;
		right: 0;
		width: 17rem;
		min-height: 100%;
		max-height: calc(100dvh - 7rem);
		display: grid;
	}
	.drawer.flipped {
		right: auto;
		left: 0;
	}
</style>
