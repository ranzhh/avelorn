<script lang="ts" module>
	/** Whether an edit on the graph stays on it or changes the table's blocks. */
	export type Mode = 'preview' | 'edit';
</script>

<script lang="ts">
	import { VIEWS, type View } from './odds';

	interface Props {
		mode: Mode;
		view: View;
	}

	let { mode = $bindable(), view = $bindable() }: Props = $props();

	const MODES: Mode[] = ['preview', 'edit'];

	const SAYS: Record<Mode | View, string> = {
		preview: 'changes stay on the graph',
		edit: "changes update the table's blocks",
		conditional: 'each chance given the step before it happened',
		marginal: 'each chance from the start of the charge'
	};
</script>

<details class="settings">
	<summary aria-label="settings">
		<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
			<circle class="teeth" cx="12" cy="12" r="8" />
			<circle class="hub" cx="12" cy="12" r="5.5" />
		</svg>
	</summary>
	<div class="sheet">
		{@render group('mode', MODES, mode, (each) => (mode = each))}
		{@render group('odds', VIEWS, view, (each) => (view = each))}
	</div>
</details>

{#snippet group<T extends string>(label: string, choices: T[], chosen: T, pick: (each: T) => void)}
	<span class="meta">{label}</span>
	<div class="choices" role="radiogroup" aria-label={label}>
		{#each choices as each}
			<span class="choice">
				<button
					role="radio"
					aria-checked={chosen === each}
					aria-describedby="says-{each}"
					class:on={chosen === each}
					onclick={() => pick(each)}>{each}</button
				>
				<span class="says" id="says-{each}">{SAYS[each as Mode | View]}</span>
			</span>
		{/each}
	</div>
{/snippet}

<style>
	.settings {
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
	summary svg {
		fill: none;
		stroke: var(--dim);
	}
	summary:hover svg {
		stroke: var(--ink);
	}
	.teeth {
		stroke-width: 4;
		stroke-dasharray: 3.1416 3.1416;
	}
	.hub {
		stroke-width: 2.5;
	}
	.settings[open] summary svg {
		stroke: var(--accent);
	}
	summary::-webkit-details-marker {
		display: none;
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
	.choices {
		display: flex;
		gap: 2px;
	}
	.choice {
		position: relative;
	}
	.choice .says {
		width: max-content;
		max-width: 16rem;
		white-space: normal;
	}
	.choice:hover .says {
		display: block;
	}
	.choices button {
		height: 22px;
		padding: 0 0.6rem;
		font-size: 12px;
		cursor: pointer;
	}
	.choices button.on {
		color: var(--on-accent);
		background: var(--accent);
		border-color: var(--accent);
	}
</style>
