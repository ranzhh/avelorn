<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<header>
	<a href="/">Avelorn</a>
	<span>unit browser</span>
</header>

<main>
	{@render children()}
</main>
