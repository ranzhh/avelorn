<script lang="ts">
	import ArmourText from '$lib/ArmourText.svelte';
	import Pane from '$lib/Pane.svelte';
	import RuleText from '$lib/RuleText.svelte';
	import Sheet from '$lib/Sheet.svelte';
	import WeaponText from '$lib/WeaponText.svelte';
	import { entry } from '$lib/corpus';
	import {
		FIRST,
		closed,
		measure,
		moved,
		opened,
		raised,
		topmost,
		type Pane as Open,
		type Subject
	} from '$lib/panes';
	import type { Armour, Reference, Rule, Unit, Weapon } from '$lib/api/client';
	import type { Snippet } from 'svelte';

	interface Props {
		/** What a block's pane shows beside its datasheet, given the block: the controls that change it. */
		options?: Snippet<[number]>;
		/** Open cold panes to the right of this, so they leave it readable. */
		beside?: HTMLElement | null;
	}

	let { options, beside = null }: Props = $props();

	let open = $state<Open[]>([]);
	let nextId = 1;
	// Entries arrive after the pane does, so a pane draws its chrome first and
	// fills in. Keyed by "subject:slug", which is what a pane is one of.
	let read = $state<Record<string, Unit | Rule | Weapon | Armour>>({});

	const GAP = 24;

	function viewport() {
		return { width: window.innerWidth, height: window.innerHeight };
	}

	/**
	 * Put one entry of the corpus on screen, or raise the pane already reading it.
	 *
	 * `from` is the pane it was followed from, so a rule opened out of a weapon
	 * opened out of a datasheet cascades down the chain rather than landing
	 * anywhere. `block` names the block on the table the pane belongs to, which
	 * is what gives it its own options.
	 */
	export async function show(
		wanted: { subject: Subject; slug: string; title: string; block?: number },
		from?: Open
	) {
		const first = beside
			? { x: beside.getBoundingClientRect().right + GAP, y: FIRST.y }
			: undefined;
		open = opened(open, { id: nextId, ...wanted }, measure(wanted), viewport(), from, first);
		nextId += 1;
		const key = `${wanted.subject}:${wanted.slug}`;
		if (read[key]) return;
		const found = await entry(wanted.subject, wanted.slug);
		if (found) read[key] = found;
	}

	/** Close the pane a block owns, once the block is gone. */
	export function forget(block: number) {
		open = open.filter((pane) => pane.block !== block);
	}

	// A reference carries the kind as well as the slug, because a printed name
	// does not say which registry holds it: "Daith's Reaper" is filed as both a
	// weapon and a rule.
	function follow(parent: Open, reference: Reference) {
		if (!reference.kind || !reference.slug) return;
		show({ subject: reference.kind, slug: reference.slug, title: reference.name }, parent);
	}

	// Escape shuts the top pane, the way it shuts any floating thing. Following
	// names down opens a stack, and closing it should not mean hunting for four
	// close buttons.
	function dismiss(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		const top = topmost(open);
		if (top) open = closed(open, top.id);
	}
</script>

<svelte:window onkeydown={dismiss} />

{#each open as pane (pane.id)}
	{@const found = read[`${pane.subject}:${pane.slug}`]}
	<Pane
		{pane}
		onraise={() => (open = raised(open, pane.id))}
		onmove={(x, y) => (open = moved(open, pane.id, x, y, measure(pane), viewport()))}
		onclose={() => (open = closed(open, pane.id))}
		{options}
	>
		{#if !found}
			<p class="pending">reading…</p>
		{:else if pane.subject === 'unit'}
			<Sheet
				unit={found as Unit}
				pricing={pane.block === undefined}
				onopen={(reference) => follow(pane, reference)}
			/>
		{:else if pane.subject === 'weapon'}
			<WeaponText weapon={found as Weapon} onopen={(reference) => follow(pane, reference)} />
		{:else if pane.subject === 'armour'}
			<ArmourText armour={found as Armour} />
		{:else}
			<RuleText rule={found as Rule} />
		{/if}
	</Pane>
{/each}
