<script lang="ts">
	import Warn from '$lib/Warn.svelte';
	import type { Armour } from '$lib/api/client';

	let { armour }: { armour: Armour } = $props();
</script>

{#if armour.notes}
	<p class="meta where"><span></span><Warn notes={[armour.notes]} /></p>
{/if}

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
