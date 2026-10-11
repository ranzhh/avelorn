<script lang="ts">
	import { page } from '$app/state';
	import Muster from '$lib/Muster.svelte';
	import { api, type Wieldable } from '$lib/api/client';
	import { usable } from '$lib/table';
	import type { Deployment } from './body';

	interface Props {
		deployment: Deployment;
		/** The width it fights at, when the deployment leaves it to the datasheet. */
		frontage: number;
		onchange: (change: Partial<Deployment>) => void;
	}

	let { deployment, frontage, onchange }: Props = $props();

	let weapons = $state<Wieldable[]>([]);

	$effect(() => {
		const { unit, size, options = [] } = deployment;
		api(page.url.origin, fetch)
			.POST('/muster', { body: { unit, size, options, frontage: null } })
			.then(({ data }) => {
				if (data) weapons = usable(data, 'melee');
			});
	});

	function reform(event: Event & { currentTarget: HTMLInputElement }) {
		const files = event.currentTarget.valueAsNumber;
		if (Number.isInteger(files) && files >= 1) onchange({ frontage: files });
	}
</script>

<Muster
	live
	unit={deployment.unit}
	size={deployment.size}
	options={deployment.options ?? []}
	onsubmit={(size, options) => onchange({ size, options })}
/>
{#if weapons.length > 1}
	<label class="field">
		<span>weapon</span>
		<select
			class="select"
			value={deployment.weapon ?? ''}
			onchange={(event) => onchange({ weapon: event.currentTarget.value || null })}
		>
			<option value="">default</option>
			{#each weapons as weapon}<option value={weapon.name}>{weapon.name}</option>{/each}
		</select>
	</label>
{/if}
<label class="field">
	<span>frontage</span>
	<input
		class="input"
		type="number"
		min="1"
		max={deployment.size}
		value={deployment.frontage ?? frontage}
		oninput={reform}
	/>
</label>
