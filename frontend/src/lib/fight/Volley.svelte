<script lang="ts">
	import type { VolleyLanes } from '$lib/api/client';
	import Drawn from './Drawn.svelte';
	import Settings from './Settings.svelte';
	import { measurer } from './measure';
	import type { View } from './odds';
	import { drawVolley } from './volley';

	interface Props {
		lanes: VolleyLanes;
	}

	let { lanes }: Props = $props();

	let open = $state<string | null>(null);
	let view = $state<View>('conditional');

	const measure = measurer();
	const drawing = $derived(drawVolley(lanes, measure, open, view));
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && (open = null)} />

<div class="volley">
	<Settings bind:view from="the volley" />
	<div class="stage">
		<Drawn
			{drawing}
			label="{lanes.units.attacker.name} shoot {lanes.units.target.name}"
			{open}
			ontoggle={(id) => (open = open === id ? null : id)}
		/>
	</div>
</div>

<style>
	.volley {
		position: relative;
		min-height: 24rem;
		border: 1px solid var(--line);
	}
	.stage {
		overflow-x: auto;
	}
</style>
