<script lang="ts">
	import type { Snippet } from 'svelte';
	import { ASIDE, LABEL, MEASURE, measure, type Pane } from '$lib/panes';

	interface Props {
		pane: Pane;
		onraise: () => void;
		onmove: (x: number, y: number) => void;
		onclose: () => void;
		children: Snippet;
		/** Shown beside the body, taking the block the pane was opened for. */
		options?: Snippet<[number]>;
	}

	let { pane, onraise, onmove, onclose, children, options }: Props = $props();

	const beside = $derived(pane.block !== undefined && options !== undefined);
	let showing = $state(true);

	// Placed at its full measure, drawn without the aside while that is folded.
	const placed = $derived(measure(pane));
	const drawn = $derived(beside && showing ? placed.width : MEASURE[pane.subject].width);

	// Where in the bar the pointer went down, so the pane moves with the grip
	// rather than jumping its corner under the cursor.
	let grip = $state<{ x: number; y: number } | null>(null);

	function grab(event: PointerEvent) {
		onraise();
		// The close button sits in this bar. Capturing the pointer retargets its
		// click to the bar, which swallows it.
		if ((event.target as Element).closest('button')) return;
		grip = { x: event.clientX - pane.x, y: event.clientY - pane.y };
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
	}

	function drag(event: PointerEvent) {
		if (!grip) return;
		onmove(event.clientX - grip.x, event.clientY - grip.y);
	}

	function release() {
		grip = null;
	}
</script>

<section
	class="pane"
	style="left: {pane.x}px; top: {pane.y}px; z-index: {100 +
		pane.z}; --pane-w: {drawn}px; --pane-h: {placed.height}px; --aside-w: {ASIDE}px"
	onpointerdowncapture={onraise}
>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<header
		class:held={grip !== null}
		onpointerdown={grab}
		onpointermove={drag}
		onpointerup={release}
		onpointercancel={release}
	>
		<span class="eyebrow">{LABEL[pane.subject]}</span>
		<h3>{pane.title}</h3>
		{#if beside}
			<button
				class="btn btn-ghost btn-sm fold"
				class:on={showing}
				onclick={() => (showing = !showing)}
				aria-expanded={showing}
			>
				options
			</button>
		{/if}
		<button class="btn btn-ghost btn-sm shut" onclick={onclose} aria-label="close">×</button>
	</header>
	<div class="split">
		<div class="body">
			{@render children()}
		</div>
		{#if beside && showing}
			<aside>
				{@render options?.(pane.block!)}
			</aside>
		{/if}
	</div>
</section>
