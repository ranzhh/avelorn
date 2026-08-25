<script lang="ts">
	import { resolve } from '$app/paths';

	import '../app.css';

	let { children } = $props();
</script>

<header>
	<a href={resolve('/')}>Avelorn</a>
	<a href={resolve('/list')}>list</a>
	<span>unit browser</span>
</header>

<main>
	{@render children()}
</main>
