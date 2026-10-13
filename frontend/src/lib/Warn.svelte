<script lang="ts">
	interface Props {
		/** What is left out, one line each; nothing is drawn without any. */
		notes: string[];
		/** Print how many beside the mark. */
		count?: boolean;
	}

	let { notes, count = false }: Props = $props();
</script>

{#if notes.length}
	<span class="warn" role="img" aria-label={notes.join('; ')}>
		⚠{#if count}<b>{notes.length}</b>{/if}
		<span class="says">
			{#each notes as note}<span>{note}</span>{/each}
		</span>
	</span>
{/if}
