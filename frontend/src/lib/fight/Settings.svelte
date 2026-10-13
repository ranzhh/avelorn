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
</script>

<details class="settings">
	<summary aria-label="settings">⚙</summary>
	<div class="sheet">
		{@render group('edits', MODES, mode, (each) => (mode = each))}
		{@render group('chances', VIEWS, view, (each) => (view = each))}
	</div>
</details>

{#snippet group<T extends string>(label: string, choices: T[], chosen: T, pick: (each: T) => void)}
	<span class="meta">{label}</span>
	<div class="choices" role="radiogroup" aria-label={label}>
		{#each choices as each}
			<button
				role="radio"
				aria-checked={chosen === each}
				class:on={chosen === each}
				onclick={() => pick(each)}>{each}</button
			>
		{/each}
	</div>
{/snippet}

<style>
	.settings {
		position: absolute;
		top: 4px;
		right: 4px;
		z-index: 2;
	}
	summary {
		list-style: none;
		width: 26px;
		height: 26px;
		display: grid;
		place-items: center;
		font-size: 16px;
		cursor: pointer;
		border: 1px solid var(--line);
		background: var(--bg);
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
		background: var(--bg);
		border: 1px solid var(--line);
		box-shadow: 0 2px 8px rgb(0 0 0 / 0.12);
		white-space: nowrap;
	}
	.choices {
		display: flex;
		gap: 2px;
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
