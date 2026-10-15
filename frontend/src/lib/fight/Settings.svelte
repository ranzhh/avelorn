<script lang="ts" module>
	/** Whether an edit on the graph stays on it or changes the table's blocks. */
	export type Mode = 'preview' | 'edit';
</script>

<script lang="ts">
	import Choices from '$lib/Choices.svelte';
	import Cog from '$lib/Cog.svelte';
	import { VIEWS, type View } from './odds';

	interface Props {
		/** Left out where an edit has no table to write back to. */
		mode?: Mode;
		view: View;
		/** What a marginal chance counts from. */
		from?: string;
	}

	let { mode = $bindable(), view = $bindable(), from = 'the charge' }: Props = $props();

	const MODES: Mode[] = ['preview', 'edit'];
</script>

<Cog>
	{#if mode}
		<Choices
			label="mode"
			choices={MODES}
			bind:chosen={mode}
			says={{ preview: 'changes stay on the graph', edit: "changes update the table's blocks" }}
		/>
	{/if}
	<Choices
		label="odds"
		choices={VIEWS}
		bind:chosen={view}
		says={{
			conditional: 'each chance given the step before it happened',
			marginal: `each chance from the start of ${from}`
		}}
	/>
</Cog>
