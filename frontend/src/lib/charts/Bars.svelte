<script lang="ts">
	import { band, percent, ticks } from './scale';

	interface Props {
		x: number;
		y: number;
		width: number;
		height: number;
		/** Chance by outcome, `chances[k]` being the chance of `least + k`. */
		least: number;
		chances: number[];
		mean: number;
		/** An outcome drawn even where it has no chance, with a rule before it. */
		rule?: number | null;
		/** The colour of each outcome's bar. */
		fill: (outcome: number) => string;
		label: string;
	}

	let { x, y, width, height, least, chances, mean, rule = null, fill, label }: Props = $props();

	const GUTTER = 24;
	const AXIS = 13;
	const BAR_MAX = 18;
	const GAP = 2;

	let hovered = $state<number | null>(null);

	const drawn = $derived.by(() => {
		const trimmed = band(chances);
		let from = least + trimmed.from;
		let to = from + trimmed.masses.length - 1;
		if (rule !== null) {
			from = Math.min(from, rule);
			to = Math.max(to, rule);
		}
		const masses = Array.from({ length: to - from + 1 }, (_, k) => chances[from + k - least] ?? 0);
		return { from, masses };
	});
	const plot = $derived(height - AXIS);
	const scale = $derived(ticks(Math.max(...drawn.masses, 0.0001)));
	const ceiling = $derived(scale[scale.length - 1]);
	const plotWidth = $derived(width - GUTTER);
	const slot = $derived(plotWidth / drawn.masses.length);
	const barWidth = $derived(Math.max(Math.min(slot - GAP, BAR_MAX), 1));
	const every = $derived(Math.max(1, Math.ceil(24 / slot)));

	const top = (mass: number) => plot - (mass / ceiling) * plot;
	const centre = (index: number) => GUTTER + slot * (index + 0.5);

	function bar(index: number, mass: number): string {
		const rise = plot - top(mass);
		if (rise <= 0) return '';
		const left = centre(index) - barWidth / 2;
		const right = left + barWidth;
		const cap = Math.min(3, barWidth / 2, rise);
		const peak = top(mass);
		return `M${left},${plot} L${left},${peak + cap} Q${left},${peak} ${left + cap},${peak} L${right - cap},${peak} Q${right},${peak} ${right},${peak + cap} L${right},${plot} Z`;
	}

	function track(event: PointerEvent) {
		const box = (event.currentTarget as SVGRectElement).getBoundingClientRect();
		const at = Math.floor(((event.clientX - box.left) / box.width) * drawn.masses.length);
		hovered = at >= 0 && at < drawn.masses.length ? at : null;
	}
</script>

<g
	class="bars"
	transform="translate({x},{y})"
	role="img"
	aria-label="{label}, {drawn.from} to {drawn.from + drawn.masses.length - 1}"
>
	{#each scale as tick}
		<line class="grid" x1={GUTTER} y1={top(tick)} x2={width} y2={top(tick)} />
		<text class="tick" x={GUTTER - 4} y={top(tick) + 3} text-anchor="end"
			>{Math.round(tick * 100)}</text
		>
	{/each}

	{#each drawn.masses as mass, index}
		{@const outcome = drawn.from + index}
		{#if bar(index, mass)}
			<path class:lit={hovered === index} d={bar(index, mass)} style:fill={fill(outcome)} />
		{/if}
		{#if outcome % every === 0}
			<text class="tick" x={centre(index)} y={plot + 11} text-anchor="middle">{outcome}</text>
		{/if}
	{/each}

	{#if rule !== null}
		{@const at = GUTTER + slot * (rule - drawn.from)}
		<line class="rule" x1={at} y1="0" x2={at} y2={plot} />
	{/if}
	{#if mean >= drawn.from - 0.5 && mean <= drawn.from + drawn.masses.length - 0.5}
		{@const at = centre(mean - drawn.from)}
		<line class="mean" x1={at} y1="0" x2={at} y2={plot} />
	{/if}
	<line class="baseline" x1={GUTTER} y1={plot} x2={width} y2={plot} />

	{#if hovered !== null}
		{@const at = Math.min(Math.max(centre(hovered), GUTTER + 30), width - 30)}
		<text class="tip" x={at} y={Math.max(top(drawn.masses[hovered]) - 5, 9)} text-anchor="middle"
			>{percent(drawn.masses[hovered])} · {drawn.from + hovered}</text
		>
	{/if}
	<rect
		role="presentation"
		x={GUTTER}
		y="0"
		width={plotWidth}
		height={plot}
		fill="transparent"
		onpointermove={track}
		onpointerleave={() => (hovered = null)}
	/>
</g>

<style>
	.tick {
		font-size: 10px;
		fill: var(--dim);
	}
	.grid {
		stroke: #eee;
	}
	.baseline {
		stroke: var(--line);
	}
	.lit {
		opacity: 0.7;
	}
	.mean {
		stroke: var(--ink);
		stroke-dasharray: 3 2;
	}
	.rule {
		stroke: var(--ink);
		stroke-width: 1.5;
	}
	.tip {
		font: 11px var(--font-mono);
		fill: var(--ink);
		paint-order: stroke;
		stroke: var(--panel);
		stroke-width: 3px;
		pointer-events: none;
	}
</style>
