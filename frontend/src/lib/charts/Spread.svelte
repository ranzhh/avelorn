<script lang="ts">
	import { band, exact, labelEvery, percent, ticks } from './scale';

	interface Props {
		/** Probability by outcome, index `k` being the chance of exactly `k`. */
		values: number[];
		/** What an index counts, plural: "models lost". */
		unit: string;
		/** The mean, ticked on the plot. */
		mean?: number;
		/** Collapsed to a row-sized sparkline until opened. */
		compact?: boolean;
	}

	let { values, unit, mean, compact = false }: Props = $props();

	const GUTTER = 30;
	const AXIS = 14;
	const PLOT = 92;
	const BAR_MAX = 18;
	const GAP = 2;

	let width = $state(0);
	let hovered = $state<number | null>(null);

	const drawn = $derived(band(values));
	const scale = $derived(ticks(Math.max(...drawn.masses, 0.0001)));
	const ceiling = $derived(scale[scale.length - 1]);
	const plotWidth = $derived(Math.max(width - GUTTER, 0));
	const slot = $derived(drawn.masses.length ? plotWidth / drawn.masses.length : 0);
	const barWidth = $derived(Math.max(Math.min(slot - GAP, BAR_MAX), 1));
	const every = $derived(labelEvery(drawn.masses.length, plotWidth));

	const y = (mass: number) => PLOT - (mass / ceiling) * PLOT;
	const centre = (index: number) => GUTTER + slot * (index + 0.5);

	// Square at the baseline, rounded at the data end: the radius belongs to the
	// value, not to the axis.
	function bar(index: number, mass: number): string {
		const height = PLOT - y(mass);
		if (height <= 0) return '';
		const left = centre(index) - barWidth / 2;
		const right = left + barWidth;
		const cap = Math.min(3, barWidth / 2, height);
		const top = y(mass);
		return `M${left},${PLOT} L${left},${top + cap} Q${left},${top} ${left + cap},${top} L${right - cap},${top} Q${right},${top} ${right},${top + cap} L${right},${PLOT} Z`;
	}

	function track(event: PointerEvent) {
		const box = (event.currentTarget as SVGRectElement).getBoundingClientRect();
		const at = Math.floor(((event.clientX - box.left) / box.width) * drawn.masses.length);
		hovered = at >= 0 && at < drawn.masses.length ? at : null;
	}

	// The sparkline form: no axes, no gutter, just the shape and the mean.
	const SPARK = { width: 74, height: 16 };
	const sparkSlot = $derived(drawn.masses.length ? SPARK.width / drawn.masses.length : 0);
	const sparkTop = $derived(Math.max(...drawn.masses, 1e-9));
</script>

{#if compact}
	<svg
		class="spark"
		width={SPARK.width}
		height={SPARK.height}
		role="img"
		aria-label="{unit}, {drawn.from} to {drawn.from + drawn.masses.length - 1}"
	>
		{#each drawn.masses as mass, index}
			{@const height = (mass / sparkTop) * (SPARK.height - 1)}
			{#if height > 0}
				<rect
					class="fill"
					x={index * sparkSlot}
					y={SPARK.height - height}
					width={Math.max(sparkSlot - 0.8, 0.6)}
					height={Math.max(height, 0.6)}
				/>
			{/if}
		{/each}
		{#if mean !== undefined}
			{@const at = (mean - drawn.from + 0.5) * sparkSlot}
			{#if at >= 0 && at <= SPARK.width}
				<line class="mean" x1={at} y1="0" x2={at} y2={SPARK.height} />
			{/if}
		{/if}
	</svg>
{:else}
	<div class="plot" bind:clientWidth={width}>
		{#if width > 0}
			<svg
				height={PLOT + AXIS}
				{width}
				role="img"
				aria-label="{unit}, {drawn.from} to {drawn.from + drawn.masses.length - 1}"
			>
				{#each scale as tick}
					<line class="grid" x1={GUTTER} y1={y(tick)} x2={width} y2={y(tick)} />
					<text class="tick" x={GUTTER - 4} y={y(tick) + 3} text-anchor="end">
						{Math.round(tick * 100)}
					</text>
				{/each}

				{#each drawn.masses as mass, index}
					{#if bar(index, mass)}
						<path class="fill" class:lit={hovered === index} d={bar(index, mass)} />
					{/if}
					{#if index % every === 0}
						<text class="tick" x={centre(index)} y={PLOT + 10} text-anchor="middle">
							{drawn.from + index}
						</text>
					{/if}
				{/each}

				{#if mean !== undefined && mean >= drawn.from}
					{@const at = GUTTER + slot * (mean - drawn.from + 0.5)}
					{#if at <= width}
						<line class="mean" x1={at} y1="0" x2={at} y2={PLOT} />
					{/if}
				{/if}

				<line class="baseline" x1={GUTTER} y1={PLOT} x2={width} y2={PLOT} />
				<rect
					role="presentation"
					x={GUTTER}
					y="0"
					width={plotWidth}
					height={PLOT}
					fill="transparent"
					onpointermove={track}
					onpointerleave={() => (hovered = null)}
				/>
			</svg>

			{#if hovered !== null}
				{@const at = hovered}
				<div
					class="tip"
					style="left: {Math.min(Math.max(centre(at), 40), width - 40)}px; top: {y(
						drawn.masses[at]
					) - 6}px"
				>
					{percent(drawn.masses[at])} · {drawn.from + at}
				</div>
			{/if}
		{/if}
	</div>

	<details>
		<summary>figures</summary>
		<table>
			<thead>
				<tr><th>{unit}</th><th class="num">chance</th></tr>
			</thead>
			<tbody>
				{#each drawn.masses as mass, index}
					<tr><td>{drawn.from + index}</td><td class="num">{exact(mass)}</td></tr>
				{/each}
			</tbody>
		</table>
	</details>
{/if}

<style>
	svg {
		display: block;
		overflow: visible;
		touch-action: none;
	}

	.spark {
		overflow: visible;
	}

	.plot {
		position: relative;
	}

	.fill {
		fill: var(--series-1);
	}

	.fill.lit {
		fill: var(--accent-ink);
	}

	.grid {
		stroke: var(--line);
		stroke-width: 1;
	}

	.baseline {
		stroke: var(--faint);
		stroke-width: 1;
	}

	.mean {
		stroke: var(--dim);
		stroke-width: 1;
		opacity: 0.8;
	}

	.tick {
		font: 9px var(--font-mono);
		fill: var(--faint);
	}

	.tip {
		position: absolute;
		transform: translate(-50%, -100%);
		padding: 1px var(--space-2);
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--ink);
		background: var(--panel);
		border: 1px solid var(--faint);
		border-radius: var(--radius-sm);
		pointer-events: none;
		white-space: nowrap;
	}

	details {
		margin-top: var(--space-2);
	}

	summary {
		cursor: pointer;
		font: var(--text-xs) / 1.5 var(--font-mono);
		color: var(--dim);
	}
</style>
