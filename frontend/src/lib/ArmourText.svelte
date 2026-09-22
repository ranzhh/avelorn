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
