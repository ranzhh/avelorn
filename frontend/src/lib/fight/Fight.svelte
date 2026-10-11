<script lang="ts">
	import type { FightLanes } from '$lib/api/client';
	import Inspect from './Inspect.svelte';
	import Lanes from './Lanes.svelte';

	let { lanes }: { lanes: FightLanes } = $props();

	let selected = $state<string | null>(null);
	let side = $state<'left' | 'right'>('right');

	function select(id: string | null, away: 'left' | 'right' = side) {
		selected = id;
		side = away;
	}
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && select(null)} />

<div class="fight">
	<div class="stage">
		<Lanes {lanes} {selected} onselect={select} />
	</div>
	{#if selected}
		<div class="drawer" class:flipped={side === 'left'}>
			<Inspect {lanes} id={selected} onclose={() => select(null)} />
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
