<script lang="ts">
	interface Props {
		size?: number;
	}

	let { size = 16 }: Props = $props();
</script>

<g class="glyph" transform="scale({size / 16})">
	<path class="ink" d="M4.5 8 L11 4 M4.5 8 L11 12" />
	<circle class="node" cx="3.5" cy="8" r="2" />
	<circle class="node" cx="12" cy="3.5" r="2" />
	<circle class="node" cx="12" cy="12.5" r="2" />
</g>

<style>
	.ink {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.2px;
	}
	.node {
		fill: var(--panel);
		stroke: currentColor;
		stroke-width: 1.2px;
	}
</style>
