<script lang="ts">
	import RuleText from '$lib/RuleText.svelte';

	let { data } = $props();
</script>

<article class="page">
	<h1>{data.rule.name}</h1>
	<RuleText rule={data.rule} />
</article>
