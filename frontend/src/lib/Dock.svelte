<script lang="ts">
	import { untrack, type Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Shown on the header row while collapsed, so closing costs space and not information. */
		value?: string;
		/** A count beside the title. */
		count?: number;
		/** More on the header row, at its far end. */
		aside?: Snippet;
		/** Where the open state is remembered. */
		keep: string;
		children: Snippet;
	}

	let { title, value = '', count, keep, aside, children }: Props = $props();

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

<details class="dock" {open} ontoggle={remember}>
	<summary>
		<h2>{title}</h2>
		{#if count !== undefined}<span class="badge num">{count}</span>{/if}
		{#if value}<b>{value}</b>{/if}
		{#if aside}<span class="end">{@render aside()}</span>{/if}
	</summary>
	<div class="body">
		{@render children()}
	</div>
</details>
