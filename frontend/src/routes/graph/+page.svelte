<script lang="ts">
	import Readings from '$lib/graph/Readings.svelte';
	import { EDGE_GAP, FRAME, NODE, layout } from '$lib/graph/layout';
	import volley from '$lib/graph/volley.json';
	import type { Program, Side, StepKind, Verdict } from '$lib/graph/types';

	const program = volley as Program;

	let collapsed = $state(
		program.blocks
			.filter((block) => block.kind === 'group' && block.collapsed)
			.map((block) => block.path)
	);

	const drawn = $derived(layout(program, collapsed));

	const SIDES: Side[] = ['this-model', 'the-enemy'];
	const MARK: Record<StepKind | 'group', string> = {
		measurement: 'M',
		decision: 'D',
		roll: 'R',
		consequence: 'C',
		group: 'G'
	};
	const VERDICTS: Verdict[] = ['applied', 'honoured', 'held', 'inapplicable'];

	const printed = (slug: string) => slug.replaceAll('-', ' ');
	const last = (path: string) => path.slice(path.lastIndexOf('/') + 1);
	const named = (rule: string) => program.rules.find((each) => each.rule === rule)?.name ?? rule;
	const bearer = (who: Side | 'core') => (who === 'core' ? 'core rules' : program.sides[who]);
	const signed = (move: number) => (move > 0 ? `+${move}` : `${move}`);

	function toggle(path: string) {
		collapsed = collapsed.includes(path)
			? collapsed.filter((each) => each !== path)
			: [...collapsed, path];
	}
</script>

<div class="head">
	<h1>{program.program}</h1>
	<div class="cluster sides">
		{#each SIDES as side}
			<span class="who {side}"><i></i>{printed(side)} · {program.sides[side]}</span>
		{/each}
	</div>
	<div class="cluster legend">
		{#each Object.entries(MARK) as [kind, mark]}
			<span><span class="mark">{mark}</span>{kind}</span>
		{/each}
	</div>
</div>

<div class="scroll">
	<div class="canvas" style="width: {drawn.width}px; height: {drawn.height}px">
		<svg width={drawn.width} height={drawn.height} aria-hidden="true">
			<defs>
				<marker
					id="edge-arrow"
					viewBox="0 0 8 8"
					refX="7"
					refY="4"
					markerWidth="6"
					markerHeight="6"
					orient="auto"
				>
					<path d="M0,1 L7,4 L0,7 Z" />
				</marker>
			</defs>
			{#each drawn.blocks.filter((block) => !block.collapsed) as frame (frame.path)}
				<rect
					class="frame"
					x={frame.box.x}
					y={frame.box.y}
					width={frame.box.width}
					height={frame.box.height}
					rx="4"
				/>
			{/each}
			{#each drawn.edges as edge}
				<line
					class="edge {edge.kind}"
					x1={edge.start.x}
					y1={edge.start.y}
					x2={edge.end.x}
					y2={edge.end.y}
					marker-end="url(#edge-arrow)"
				/>
			{/each}
			{#each drawn.landings as landing}
				<line
					class="landing {landing.verdict}"
					x1={landing.start.x}
					y1={landing.start.y}
					x2={landing.end.x}
					y2={landing.end.y}
				/>
			{/each}
		</svg>

		{#each drawn.blocks as block (block.path)}
			{#if block.collapsed}
				<article
					class="card group"
					style="left: {block.box.x}px; top: {block.box.y}px; width: {block.box
						.width}px; height: {block.box.height}px"
				>
					<header>
						<span class="mark" title="group">{MARK.group}</span>
						<h3>{printed(last(block.path))}</h3>
					</header>
					<div class="times">
						<span class="label">×</span><Readings readings={block.multiplier} />
					</div>
					<span class="meta">
						{program.nodes.filter((node) => node.path.startsWith(`${block.path}/`)).length} steps
					</span>
					<button class="btn btn-ghost btn-sm fold" onclick={() => toggle(block.path)}
						>expand</button
					>
				</article>
			{:else}
				<div
					class="frame-head"
					style="left: {block.box.x}px; top: {block.box.y}px; width: {block.box
						.width}px; height: {FRAME.header}px"
				>
					<span class="mark" title={block.block.kind}>{MARK.group}</span>
					<h3>{printed(last(block.path))}</h3>
					{#if block.block.kind === 'group'}
						<span class="times"
							><span class="label">×</span><Readings readings={block.multiplier} /></span
						>
						<button class="btn btn-ghost btn-sm fold" onclick={() => toggle(block.path)}>
							collapse
						</button>
					{/if}
				</div>
			{/if}
		{/each}

		{#each drawn.steps as step (step.path)}
			{@const node = step.node}
			<article
				class="card {node.side}"
				style="left: {step.box.x}px; top: {step.box.y}px; width: {step.box.width}px; height: {step
					.box.height}px"
			>
				<header>
					<span class="mark" title={node.kind}>{MARK[node.kind]}</span>
					<h3>{printed(node.step)}</h3>
				</header>
				<span class="side">{printed(node.side)}</span>
				{#if node.kind === 'roll'}
					<Readings readings={[node.target]} width={NODE.width - 24} />
					{#each node.modifiers as modifier}
						<span class="modifier">
							<span>{named(modifier.rule)}</span>
							<b class="num">{signed(modifier.move)}</b>
						</span>
					{/each}
				{:else if node.kind === 'decision'}
					<span class="meta">{node.options.join(' / ')}</span>
				{/if}
			</article>
		{/each}

		{#each drawn.edges as edge}
			<div
				class="readings"
				style="left: {(edge.start.x + edge.end.x) / 2}px; top: {edge.start.y}px; width: {EDGE_GAP -
					24}px"
			>
				<Readings readings={edge.readings} width={EDGE_GAP - 24} />
			</div>
		{/each}

		{#each drawn.rail as placed (placed.rule.rule)}
			<article
				class="card rule"
				style="left: {placed.box.x}px; top: {placed.box.y}px; width: {placed.box
					.width}px; height: {placed.box.height}px"
			>
				<h3>{placed.rule.name}</h3>
				<span class="meta">{bearer(placed.rule.bearer)}</span>
			</article>
		{/each}

		{#each drawn.landings as landing}
			<span
				class="verdict {landing.verdict}"
				style="left: {(landing.start.x + landing.end.x) / 2}px; top: {(landing.start.y +
					landing.end.y) /
					2}px"
			>
				{landing.verdict}
			</span>
		{/each}
	</div>
</div>

<section class="unmodelled">
	<h2>not modelled</h2>
	{#if drawn.unmodelled.length}
		<ul>
			{#each drawn.unmodelled as rule (rule.rule)}
				<li><b>{rule.name}</b> <span class="meta">{bearer(rule.bearer)}</span></li>
			{/each}
		</ul>
	{:else}
		<span class="meta">none</span>
	{/if}
	<div class="cluster legend">
		{#each VERDICTS as verdict}
			<span class="verdict {verdict}">{verdict}</span>
		{/each}
	</div>
</section>

<style>
	.head {
		display: flex;
		align-items: baseline;
		gap: var(--space-5);
		padding: 0 var(--space-3) var(--space-3);
	}

	.sides {
		gap: var(--space-4);
	}

	.who {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--dim);
	}

	.who i {
		width: 8px;
		height: 8px;
		border-radius: 1px;
	}

	.who.this-model i {
		background: var(--series-1);
	}

	.who.the-enemy i {
		background: var(--series-2);
	}

	.legend {
		margin-left: auto;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--dim);
	}

	.legend > span {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}

	.scroll {
		overflow-x: auto;
		padding: 0 var(--space-3);
	}

	.canvas {
		position: relative;
	}

	svg {
		position: absolute;
		inset: 0;
	}

	marker path {
		fill: var(--faint);
	}

	.frame {
		fill: color-mix(in oklab, var(--panel) 60%, var(--plane));
		stroke: var(--line);
		stroke-dasharray: 4 3;
	}

	.edge {
		stroke: var(--faint);
		stroke-width: 1;
	}

	.edge.times {
		stroke-dasharray: 3 3;
	}

	.landing {
		stroke: var(--line);
		stroke-width: 1;
	}

	.landing.applied {
		stroke: var(--faint);
	}

	.card,
	.frame-head {
		position: absolute;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.card {
		padding: var(--space-2) var(--space-3);
		background: var(--panel);
		border: 1px solid var(--line);
		border-left-width: 3px;
		border-radius: var(--radius-md);
	}

	.card.this-model {
		border-left-color: var(--series-1);
	}

	.card.the-enemy {
		border-left-color: var(--series-2);
	}

	.card.group {
		border-left-color: var(--faint);
		border-style: dashed;
	}

	.card.rule {
		border-left-color: var(--line);
		background: var(--sunken);
	}

	.card header,
	.frame-head {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}

	.frame-head {
		padding: 0 var(--space-3);
	}

	.frame-head .times {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-1);
	}

	.card h3,
	.frame-head h3 {
		font-size: var(--text-sm);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.mark {
		display: inline-grid;
		place-items: center;
		width: 16px;
		height: 16px;
		flex: none;
		font: 600 var(--text-xs) / 1 var(--font-mono);
		color: var(--ink);
		background: var(--neutral);
		border-radius: var(--radius-sm);
	}

	.side,
	.label {
		font-size: var(--text-xs);
		color: var(--dim);
	}

	.times {
		display: flex;
		align-items: baseline;
		gap: var(--space-1);
	}

	.modifier {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--dim);
	}

	.modifier b {
		font-weight: 400;
		color: var(--ink);
	}

	.fold {
		align-self: flex-start;
		margin-left: auto;
		font-family: var(--font-mono);
		color: var(--accent-ink);
	}

	.card.group .fold {
		margin-top: auto;
		margin-left: 0;
	}

	.readings {
		position: absolute;
		transform: translate(-50%, calc(-100% - 6px));
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.verdict {
		position: absolute;
		transform: translate(-50%, -50%);
		padding: 0 var(--space-2);
		font: var(--text-xs) / 1.7 var(--font-mono);
		color: var(--dim);
		background: var(--sunken);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		white-space: nowrap;
	}

	.verdict.applied {
		color: var(--pos);
	}

	.verdict.held {
		color: var(--neg);
	}

	.verdict.inapplicable {
		color: var(--faint);
	}

	.unmodelled {
		display: flex;
		align-items: baseline;
		gap: var(--space-4);
		padding: var(--space-4) var(--space-3) 0;
	}

	.unmodelled ul {
		display: flex;
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.unmodelled b {
		font-weight: 400;
	}

	.unmodelled .legend {
		font-size: var(--text-xs);
	}

	.unmodelled .verdict {
		position: static;
		transform: none;
	}
</style>
