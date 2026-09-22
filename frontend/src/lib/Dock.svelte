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
