<script lang="ts">
	import type { ChargeArc, FightBody } from '$lib/api/client';
	import type { Box } from './faces';

	interface Props {
		box: Box;
		/** The charge as last asked for, which the inputs show while a redraw is on its way. */
		charge: NonNullable<FightBody['charge']>;
		open: boolean;
		oncharge: (change: { full_inches?: number; arc?: ChargeArc }) => void;
	}

	let { box, charge, open, oncharge }: Props = $props();

	const ARCS: ChargeArc[] = ['front', 'flank', 'rear'];

	function inches(event: Event & { currentTarget: HTMLInputElement }) {
		const value = event.currentTarget.valueAsNumber;
		if (Number.isInteger(value) && value >= 0) oncharge({ full_inches: value });
	}
</script>

<g class="field" class:open transform="translate({box.x},{box.y})">
	<rect class="card" width={box.width} height={box.height} rx="8" />
	<text class="title" x="12" y="23">Battlefield</text>
	<text class="small" x="12" y="45">distance</text>
	<foreignObject x="12" y="51" width={box.width - 24} height="26">
		<label class="inches">
			<input
				class="input"
				type="number"
				min="0"
				value={charge.full_inches}
				oninput={inches}
				aria-label="distance"
			/><span>in</span>
		</label>
	</foreignObject>
	<text class="small" x="12" y="93">arc struck</text>
	<foreignObject x="12" y="99" width={box.width - 24} height="26">
		<select
			class="select"
			value={charge.arc}
			onchange={(event) => oncharge({ arc: event.currentTarget.value as ChargeArc })}
			aria-label="arc struck"
		>
			{#each ARCS as arc}<option value={arc}>{arc}</option>{/each}
		</select>
	</foreignObject>
</g>

<style>
	text {
		fill: var(--ink);
	}
	.small {
		font-size: 11px;
		fill: var(--dim);
	}
	.title {
		font-weight: 600;
	}
	.card {
		fill: var(--panel);
		stroke: #bdbdbd;
	}
	.open .card {
		stroke: var(--ink);
		stroke-width: 2;
	}
	.inches {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font: 12px var(--font-mono);
	}
	.inches input,
	select {
		width: 100%;
		height: 24px;
		padding: 0 0.4rem;
		font: 12px var(--font-mono);
		background: #fafafa;
	}
	.inches input {
		width: 5rem;
	}
</style>
