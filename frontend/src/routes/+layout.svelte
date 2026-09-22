<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	import '../minimal.css';

	let { children } = $props();

	const NAV = [
		{ href: resolve('/'), label: 'datasheets', at: '/' },
		{ href: resolve('/list'), label: 'list', at: '/list' },
		{ href: resolve('/table'), label: 'table', at: '/table' },
		{ href: resolve('/graph'), label: 'graph', at: '/graph' }
	];

	const here = $derived(page.url.pathname.replace(/\/$/, '') || '/');
</script>

<header class="site-header">
	<a class="mark" href={resolve('/')}>avelorn</a>
	<nav>
		{#each NAV as item}
			<a href={item.href} class:on={here === item.at}>{item.label}</a>
		{/each}
	</nav>
</header>

<main>
	{@render children()}
</main>
