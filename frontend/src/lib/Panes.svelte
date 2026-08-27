<script lang="ts">
	import Pane from '$lib/Pane.svelte';
	import RuleText from '$lib/RuleText.svelte';
	import Sheet from '$lib/Sheet.svelte';
	import { datasheet } from '$lib/datasheets';
	import {
		MEASURE,
		closed,
		moved,
		opened,
		raised,
		type Pane as Open,
		type Subject
	} from '$lib/panes';
	import { rule } from '$lib/rules';
	import type { Rule, Unit } from '$lib/api/client';

	let open = $state<Open[]>([]);
	let nextId = 1;
	// Entries arrive after the pane does, so a pane draws its chrome first and
	// fills in. Keyed by "subject:slug", which is what a pane is one of.
	let read = $state<Record<string, Unit | Rule>>({});

	function viewport() {
		return { width: window.innerWidth, height: window.innerHeight };
	}

	/**
	 * Put a datasheet or a rule on screen, or raise the pane already reading it.
	 *
	 * `from` is the pane it was followed from, so a rule opened out of a
	 * datasheet cascades off that datasheet rather than landing anywhere.
	 */
	export async function show(subject: Subject, slug: string, title: string, from?: Open) {
		open = opened(open, { id: nextId, subject, slug, title }, MEASURE[subject], viewport(), from);
		nextId += 1;
		const key = `${subject}:${slug}`;
		if (read[key]) return;
		const entry = subject === 'unit' ? await datasheet(slug) : await rule(slug);
		if (entry) read[key] = entry;
	}

	function follow(parent: Open, slug: string, name: string) {
		show('rule', slug, name, parent);
	}

	// Escape shuts the top pane, the way it shuts any floating thing. Following
	// rules down opens a stack, and closing it should not mean hunting for four
	// close buttons.
	function dismiss(event: KeyboardEvent) {
		if (event.key !== 'Escape' || open.length === 0) return;
		open = open.slice(0, -1);
	}
</script>

<svelte:window onkeydown={dismiss} />

{#each open as pane, depth (pane.id)}
	{@const entry = read[`${pane.subject}:${pane.slug}`]}
	<Pane
		{pane}
		{depth}
		onraise={() => (open = raised(open, pane.id))}
		onmove={(x, y) => (open = moved(open, pane.id, x, y, MEASURE[pane.subject], viewport()))}
		onclose={() => (open = closed(open, pane.id))}
	>
		{#if !entry}
			<p class="pending">reading…</p>
		{:else if pane.subject === 'unit'}
			<Sheet unit={entry as Unit} onrule={(slug, name) => follow(pane, slug, name)} />
		{:else}
			<RuleText rule={entry as Rule} />
		{/if}
	</Pane>
{/each}

<style>
	.pending {
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}
</style>
