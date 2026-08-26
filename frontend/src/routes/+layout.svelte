<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	import '../app.css';

	let { children } = $props();

	// The table is a screen rather than a column of prose, so it takes the width.
	const wide = $derived(page.url.pathname.endsWith('/table'));
</script>

<header>
	<a href={resolve('/')}>Avelorn</a>
	<a href={resolve('/list')}>list</a>
	<a href={resolve('/table')}>table</a>
	<span>unit browser</span>
</header>

<main class:wide>
	{@render children()}
</main>

<style>
	main.wide {
		max-width: none;
	}
</style>
