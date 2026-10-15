<script lang="ts" generics="T extends string">
	interface Props {
		label: string;
		choices: readonly T[];
		chosen: T;
		/** Shown on hover, one line per choice. */
		says: Record<T, string>;
		/** How each choice is printed, where not as itself. */
		names?: Partial<Record<T, string>>;
	}

	let { label, choices, chosen = $bindable(), says, names = {} }: Props = $props();
</script>

<span class="meta">{label}</span>
<div class="choices" role="radiogroup" aria-label={label}>
	{#each choices as each}
		<span class="choice">
			<button
				role="radio"
				aria-checked={chosen === each}
				aria-describedby="says-{label}-{each}"
				class:on={chosen === each}
				onclick={() => (chosen = each)}>{names[each] ?? each}</button
			>
			<span class="says" id="says-{label}-{each}">{says[each]}</span>
		</span>
	{/each}
</div>

<style>
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
