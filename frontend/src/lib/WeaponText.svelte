<script lang="ts">
	import Chips from '$lib/Chips.svelte';
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

{#if weapon.weapon_type}<p class="meta">{weapon.weapon_type}</p>{/if}

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

{#if weapon.notes}
	<h4>not covered</h4>
	<p class="meta">{weapon.notes}</p>
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

	table {
		margin-top: var(--space-2);
	}

	th,
	td {
		padding: 1px var(--space-1);
	}

	.who {
		width: 99%;
		color: var(--ink);
	}
</style>
