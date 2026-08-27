<script lang="ts">
	import type { Snippet } from 'svelte';
	import { LABEL, MEASURE, type Pane } from '$lib/panes';

	interface Props {
		pane: Pane;
		/** Where in the stack this sits; the last pane drawn is the top one. */
		depth: number;
		onraise: () => void;
		onmove: (x: number, y: number) => void;
		onclose: () => void;
		children: Snippet;
	}

	let { pane, depth, onraise, onmove, onclose, children }: Props = $props();

	const measure = $derived(MEASURE[pane.subject]);

	// Where in the bar the pointer went down, so the pane moves with the grip
	// rather than jumping its corner under the cursor.
	let grip = $state<{ x: number; y: number } | null>(null);

	function grab(event: PointerEvent) {
		onraise();
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
		depth}; --pane-w: {measure.width}px; --pane-h: {measure.height}px"
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
		<button class="btn btn-ghost btn-sm shut" onclick={onclose} aria-label="close">×</button>
	</header>
	<div class="body">
		{@render children()}
	</div>
</section>

<style>
	.pane {
		position: fixed;
		width: var(--pane-w);
		max-height: var(--pane-h);
		display: flex;
		flex-direction: column;
		background: var(--panel);
		border: 1px solid var(--faint);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow);
	}

	header {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
		border-bottom: 1px solid var(--line);
		cursor: grab;
		user-select: none;
		touch-action: none;
	}

	header.held {
		cursor: grabbing;
	}

	h3 {
		flex: 1;
		font-size: var(--text-sm);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.eyebrow {
		flex: none;
	}

	.shut {
		flex: none;
		align-self: center;
		font-size: var(--text-base);
		line-height: 1;
		padding: 0 var(--space-2);
	}

	.body {
		overflow-y: auto;
		padding: var(--space-3);
	}
</style>
