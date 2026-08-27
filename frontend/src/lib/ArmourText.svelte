<script lang="ts">
	import type { Armour } from '$lib/api/client';

	let { armour }: { armour: Armour } = $props();
</script>

<table>
	<tbody>
		<tr>
			<td>armour value</td>
			<td class="num">{armour.armour_value ? `${armour.armour_value}+` : '–'}</td>
		</tr>
		<tr>
			<td>improves by</td>
			<td class="num">{armour.armour_value_improvement ?? '–'}</td>
		</tr>
	</tbody>
</table>

{#if armour.notes}
	<h4>not covered</h4>
	<p class="meta">{armour.notes}</p>
{/if}

<style>
	h4 {
		margin: var(--space-3) 0 var(--space-1);
		font: 600 var(--text-xs) / 1 var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--dim);
	}

	.meta {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	td:first-child {
		color: var(--dim);
	}
</style>
