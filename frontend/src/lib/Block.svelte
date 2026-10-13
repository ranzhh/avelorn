<script lang="ts">
	import Muster from '$lib/Muster.svelte';
	import { usable, type Placed } from '$lib/table';

	interface Props {
		standing: Placed;
		onrecost: (size: number, options: string[]) => void;
		onamend: (change: Partial<Placed>) => void;
		onreform: (files: number) => void;
		onturn: (facing: number) => void;
		onremove: () => void;
	}

	let { standing, onrecost, onamend, onreform, onturn, onremove }: Props = $props();

	const print = $derived(standing.block.footprint);
	const melee = $derived(usable(standing.block, 'melee'));
	const missile = $derived(usable(standing.block, 'missile'));

	function reform(event: Event & { currentTarget: HTMLInputElement }) {
		const files = event.currentTarget.valueAsNumber;
		if (Number.isInteger(files) && files >= 1 && files !== print?.files) onreform(files);
	}
</script>

<Muster
	live
	unit={standing.block.unit}
	size={standing.block.size}
	options={standing.block.options.map((option) => option.id)}
	onsubmit={onrecost}
/>
<div class="field"><span>points</span><span class="num">{standing.block.points}</span></div>
{#if melee.length > 1}
	<label class="field">
		<span>melee</span>
		<select
			class="select"
			value={standing.melee}
			onchange={(event) => onamend({ melee: event.currentTarget.value })}
		>
			<option value="">default</option>
			{#each melee as weapon}<option value={weapon.name}>{weapon.name}</option>{/each}
		</select>
	</label>
{/if}
{#if missile.length > 1}
	<label class="field">
		<span>missile</span>
		<select
			class="select"
			value={standing.missile}
			onchange={(event) => onamend({ missile: event.currentTarget.value })}
		>
			<option value="">default</option>
			{#each missile as weapon}<option value={weapon.name}>{weapon.name}</option>{/each}
		</select>
	</label>
{/if}
{#if print}
	<label class="field">
		<span>files</span>
		<span class="cluster tight">
			<input
				class="input"
				type="number"
				min="1"
				max={standing.block.size}
				value={print.files}
				onchange={reform}
			/>
			<span class="pill">×{print.ranks}</span>
		</span>
	</label>
{/if}
<div class="field">
	<span>facing</span>
	<span class="cluster tight">
		<span class="num">{standing.facing}°</span>
		<button class="btn btn-sm" disabled={standing.facing === 0} onclick={() => onturn(0)}>
			face up
		</button>
	</span>
</div>
<div class="cluster acts">
	<button class="btn btn-sm neg" onclick={onremove}>remove</button>
</div>
