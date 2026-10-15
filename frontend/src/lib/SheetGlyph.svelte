<script lang="ts">
	interface Props {
		/** Where its top-left corner stands, in the drawing's own units. */
		x?: number;
		y?: number;
		size?: number;
	}

	let { x = 0, y = 0, size = 16 }: Props = $props();
</script>

<g class="glyph" transform="translate({x} {y}) scale({size / 16})">
	<path class="page" d="M3 1.5 H10 L13 4.5 V14.5 H3 Z" />
	<path class="ink" d="M10 1.5 V4.5 H13 M5 7.5 H11 M5 10 H11 M5 12.5 H9" />
</g>

<style>
	.page {
		fill: var(--panel);
		stroke: currentColor;
		stroke-width: 1.2px;
		stroke-linejoin: round;
	}
	.ink {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.2px;
		stroke-linecap: round;
	}
</style>
