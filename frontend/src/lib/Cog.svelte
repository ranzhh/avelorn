<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	let open = $state(false);
	let cog = $state<HTMLDetailsElement | null>(null);

	function away(event: PointerEvent) {
		if (open && !cog?.contains(event.target as Node)) open = false;
	}
</script>

<svelte:window
	onpointerdown={away}
	onkeydown={(event) => event.key === 'Escape' && (open = false)}
/>

<details class="cog" bind:open bind:this={cog}>
	<summary aria-label="settings">
		<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
			<circle class="teeth" cx="12" cy="12" r="8" />
			<circle class="hub" cx="12" cy="12" r="5.5" />
		</svg>
	</summary>
	<div class="sheet">
		{@render children()}
	</div>
</details>

<style>
	.cog {
		position: absolute;
		top: 4px;
		right: 4px;
		z-index: 2;
		padding: 0;
		border: 0;
	}
	summary {
		list-style: none;
		width: 26px;
		height: 26px;
		display: grid;
		place-items: center;
		cursor: pointer;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary svg {
		width: 18px;
		height: 18px;
		border: 0;
		fill: none;
		stroke: var(--dim);
	}
	summary:hover svg {
		stroke: var(--ink);
	}
	.cog[open] summary svg {
		stroke: var(--accent);
	}
	.teeth {
		stroke-width: 4;
		stroke-dasharray: 3.1416 3.1416;
	}
	.hub {
		stroke-width: 2.5;
	}
	.sheet {
		position: absolute;
		right: 0;
		top: 30px;
		display: grid;
		grid-template-columns: auto auto;
		gap: 6px 10px;
		align-items: center;
		padding: 8px 10px;
		background: var(--panel);
		border: 1px solid var(--line);
		box-shadow: 0 2px 8px rgb(0 0 0 / 0.12);
		white-space: nowrap;
	}
</style>
