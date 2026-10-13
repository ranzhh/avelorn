<script lang="ts">
	import Chips from '$lib/Chips.svelte';
	import Warn from '$lib/Warn.svelte';
	import type { Reference, Weapon } from '$lib/api/client';

	interface Props {
		weapon: Weapon;
		onopen: (reference: Reference) => void;
	}

	let { weapon, onopen }: Props = $props();

	/** Printed as the entry prints it: an absolute value, or an offset on the wielder's. */
	function strength(profile: Weapon['profiles'][number]): string {
		const { base, modifier } = profile.S;
		if (base !== null && base !== undefined) return `${base}`;
		return modifier ? `S${modifier > 0 ? '+' : ''}${modifier}` : 'S';
	}
</script>

<p class="meta where">
	<span>{weapon.weapon_type ?? ''}</span>
	<Warn notes={weapon.notes ? [weapon.notes] : []} />
</p>

<table>
	<thead>
		<tr>
			<th></th>
			<th class="num">R</th>
			<th class="num">S</th>
			<th class="num">AP</th>
		</tr>
	</thead>
	<tbody>
		{#each weapon.profiles as profile}
			<tr>
				<td class="who">{profile.name ?? '–'}</td>
				<td class="num">{profile.R}</td>
				<td class="num">{strength(profile)}</td>
				<td class="num">{profile.AP || '–'}</td>
			</tr>
		{/each}
	</tbody>
</table>

<!-- Per profile, not pooled: a weapon with two need not print the same on both. -->
{#each weapon.profiles as profile}
	{#if profile.special_rules?.length}
		<h4>{profile.name ? `${profile.name} rules` : 'special rules'}</h4>
		<Chips of={profile.special_rules} {onopen} />
	{/if}
{/each}
