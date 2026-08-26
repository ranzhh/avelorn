<script lang="ts">
	import { untrack, type Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Shown on the header row while collapsed, so closing costs space and not information. */
		value?: string;
		/** Where the open state is remembered. */
		keep: string;
		children: Snippet;
	}

	let { title, value = '', keep, children }: Props = $props();

	const KEY = $derived(`avelorn:dock:${keep}`);

	let open = $state(true);

	$effect(() => {
		const saved = untrack(() => localStorage.getItem(KEY));
		if (saved !== null) open = saved === '1';
	});

	function remember(event: Event) {
		open = (event.currentTarget as HTMLDetailsElement).open;
		localStorage.setItem(KEY, open ? '1' : '0');
	}
</script>

<details {open} ontoggle={remember}>
	<summary>
		<h2>{title}</h2>
		{#if value}<b>{value}</b>{/if}
	</summary>
	<div class="body">
		{@render children()}
	</div>
</details>

<style>
	details {
		border-bottom: 1px solid var(--line);
	}

	summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		cursor: pointer;
		list-style: none;
		user-select: none;
	}

	summary::-webkit-details-marker {
		display: none;
	}

	summary::before {
		content: '';
		flex: none;
		width: 0;
		height: 0;
		border-left: 4px solid var(--faint);
		border-top: 3px solid transparent;
		border-bottom: 3px solid transparent;
		transition: transform var(--transition);
	}

	details[open] > summary::before {
		transform: rotate(90deg);
	}

	summary:hover h2 {
		color: var(--ink);
	}

	summary b {
		margin-left: auto;
		font: var(--text-xs) / 1 var(--font-mono);
		font-weight: 400;
		color: var(--dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.body {
		padding: 0 var(--space-3) var(--space-3);
	}
</style>
