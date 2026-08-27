<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	import '../app.css';

	let { children } = $props();

	const NAV = [
		{ href: resolve('/'), label: 'datasheets', at: '/' },
		{ href: resolve('/list'), label: 'list', at: '/list' }
	];

	const here = $derived(page.url.pathname.replace(/\/$/, '') || '/');
</script>

<header>
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

<style>
	header {
		display: flex;
		align-items: baseline;
		gap: var(--space-4);
		padding: var(--space-2) var(--space-3);
		background: var(--panel);
		border-bottom: 1px solid var(--line);
	}

	.mark {
		font-weight: 600;
		color: var(--ink);
		letter-spacing: 0.02em;
	}

	.mark:hover {
		text-decoration: none;
	}

	nav {
		display: flex;
		gap: var(--space-3);
		font-size: var(--text-sm);
	}

	nav a {
		color: var(--dim);
	}

	nav a:hover {
		color: var(--ink);
		text-decoration: none;
	}

	nav a.on {
		color: var(--ink);
		box-shadow: inset 0 -1px 0 var(--accent);
	}

	main {
		padding: var(--space-4) 0 var(--space-6);
	}
</style>
