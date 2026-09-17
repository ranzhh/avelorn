<script lang="ts">
	import Readings from './Readings.svelte';
	import { FRAME, MARGIN, caption, fitted, layout, moved, type Moves, type Point } from './layout';
	import type { Program, Side, StepKind, Verdict } from '$lib/graph/types';

	let { program }: { program: Program } = $props();

	let folded = $state<Record<string, boolean>>({});
	const collapsed = $derived(
		program.blocks
			.filter((block) => block.kind === 'group' && (folded[block.path] ?? block.collapsed))
			.map((block) => block.path)
	);
	let moves = $state<Moves>({});
	let canvasWidth = $state(0);

	const metrics = $derived(fitted(program, collapsed, Math.max(canvasWidth - 2 * MARGIN, 1)));
	const drawn = $derived(moved(layout(program, collapsed, metrics), moves));

	type Pick = { kind: 'step' | 'block' | 'rule'; id: string };
	let selected = $state<Pick | null>(null);

	const step = $derived(
		selected?.kind === 'step' ? drawn.steps.find((each) => each.path === selected!.id) : undefined
	);
	const block = $derived(
		selected?.kind === 'block' ? drawn.blocks.find((each) => each.path === selected!.id) : undefined
	);
	const rule = $derived(
		selected?.kind === 'rule' ? program.rules.find((each) => each.rule === selected!.id) : undefined
	);

	const SIDES: Side[] = ['this-model', 'the-enemy'];
	const MARK: Record<StepKind | 'group', string> = {
		measurement: 'M',
		decision: 'D',
		roll: 'R',
		consequence: 'C',
		group: 'G'
	};
	const VERDICTS: Verdict[] = ['applied', 'honoured', 'held', 'inapplicable'];
	const STRIP = 236;

	const printed = (slug: string) => slug.replaceAll('-', ' ');
	const last = (path: string) => path.slice(path.lastIndexOf('/') + 1);
	const named = (id: string) => program.rules.find((each) => each.rule === id)?.name ?? id;
	const bearer = (who: Side | 'core') => (who === 'core' ? 'core rules' : program.sides[who]);
	const signed = (move: number) => (move > 0 ? `+${move}` : `${move}`);
	const is = (kind: Pick['kind'], id: string) => selected?.kind === kind && selected.id === id;

	function toggle(path: string) {
		folded = { ...folded, [path]: !collapsed.includes(path) };
	}

	let grip = $state<{ id: string; x: number; y: number; from: Point } | null>(null);

	function grab(event: PointerEvent, pick: Pick) {
		if ((event.target as Element).closest('button')) return;
		selected = pick;
		grip = {
			id: pick.id,
			x: event.clientX,
			y: event.clientY,
			from: moves[pick.id] ?? { x: 0, y: 0 }
		};
		(event.currentTarget as Element).setPointerCapture(event.pointerId);
	}

	function drag(event: PointerEvent) {
		if (!grip) return;
		moves = {
			...moves,
			[grip.id]: {
				x: grip.from.x + event.clientX - grip.x,
				y: grip.from.y + event.clientY - grip.y
			}
		};
	}

	function release() {
		grip = null;
	}

	function key(event: KeyboardEvent, pick: Pick) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			selected = pick;
		}
	}
</script>

<div class="shell">
	<div class="stage">
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

		<div class="scroll" bind:clientWidth={canvasWidth}>
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
					{#each drawn.blocks.filter((each) => !each.collapsed) as frame (frame.path)}
						<rect
							class="frame"
							class:on={is('block', frame.path)}
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
							class:on={is('rule', landing.rule)}
							x1={landing.start.x}
							y1={landing.start.y}
							x2={landing.end.x}
							y2={landing.end.y}
						/>
					{/each}
				</svg>

				{#each drawn.blocks as each (each.path)}
					{@const pick = { kind: 'block', id: each.path } as const}
					{#if each.collapsed}
						<div
							class="card group"
							class:on={is('block', each.path)}
							class:held={grip?.id === each.path}
							role="button"
							tabindex="0"
							style="left: {each.box.x}px; top: {each.box.y}px; width: {each.box
								.width}px; height: {each.box.height}px"
							onpointerdown={(event) => grab(event, pick)}
							onpointermove={drag}
							onpointerup={release}
							onpointercancel={release}
							onkeydown={(event) => key(event, pick)}
						>
							<header>
								<span class="mark" title="group">{MARK.group}</span>
								<h3>{printed(last(each.path))}</h3>
							</header>
							<span class="side">{each.steps.length} steps · {caption(each.multiplier)}</span>
							<button class="btn btn-ghost btn-sm fold" onclick={() => toggle(each.path)}>
								expand
							</button>
						</div>
					{:else}
						<div
							class="frame-head"
							class:held={grip?.id === each.path}
							role="button"
							tabindex="0"
							style="left: {each.box.x}px; top: {each.box.y}px; width: {each.box
								.width}px; height: {FRAME.header}px"
							onpointerdown={(event) => grab(event, pick)}
							onpointermove={drag}
							onpointerup={release}
							onpointercancel={release}
							onkeydown={(event) => key(event, pick)}
						>
							<span class="mark" title={each.block.kind}>{MARK.group}</span>
							<h3>{printed(last(each.path))}</h3>
							{#if each.block.kind === 'group'}
								<span class="side">× {caption(each.multiplier)}</span>
								<button class="btn btn-ghost btn-sm fold" onclick={() => toggle(each.path)}>
									collapse
								</button>
							{/if}
						</div>
					{/if}
				{/each}

				{#each drawn.steps as placed (placed.path)}
					{@const node = placed.node}
					{@const pick = { kind: 'step', id: placed.path } as const}
					<div
						class="card {node.side}"
						class:on={is('step', placed.path)}
						class:held={grip?.id === placed.path}
						role="button"
						tabindex="0"
						style="left: {placed.box.x}px; top: {placed.box.y}px; width: {placed.box
							.width}px; height: {placed.box.height}px"
						onpointerdown={(event) => grab(event, pick)}
						onpointermove={drag}
						onpointerup={release}
						onpointercancel={release}
						onkeydown={(event) => key(event, pick)}
					>
						<header>
							<span class="mark" title={node.kind}>{MARK[node.kind]}</span>
							<h3>{printed(node.step)}</h3>
						</header>
						<span class="side">{printed(node.side)}</span>
					</div>
				{/each}

				{#each drawn.edges as edge}
					{#if caption(edge.readings)}
						<span
							class="caption"
							style="left: {(edge.start.x + edge.end.x) / 2}px; top: {(edge.start.y + edge.end.y) /
								2}px"
						>
							{caption(edge.readings)}
						</span>
					{/if}
				{/each}

				{#each drawn.rail as placed (placed.rule.rule)}
					{@const pick = { kind: 'rule', id: placed.rule.rule } as const}
					<div
						class="card rule"
						class:on={is('rule', placed.rule.rule)}
						class:held={grip?.id === placed.rule.rule}
						role="button"
						tabindex="0"
						style="left: {placed.box.x}px; top: {placed.box.y}px; width: {placed.box
							.width}px; height: {placed.box.height}px"
						onpointerdown={(event) => grab(event, pick)}
						onpointermove={drag}
						onpointerup={release}
						onpointercancel={release}
						onkeydown={(event) => key(event, pick)}
					>
						<h3>{placed.rule.name}</h3>
						<span class="side">{bearer(placed.rule.bearer)}</span>
					</div>
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

		<footer class="unmodelled">
			<span class="eyebrow">not modelled</span>
			{#if drawn.unmodelled.length}
				{#each drawn.unmodelled as each, index (each.rule)}
					<span>{index ? '· ' : ''}{each.name} <span class="meta">{bearer(each.bearer)}</span></span
					>
				{/each}
			{:else}
				<span class="meta">none</span>
			{/if}
			<span class="cluster legend">
				{#each VERDICTS as verdict}
					<span class="verdict {verdict}">{verdict}</span>
				{/each}
			</span>
		</footer>
	</div>

	<aside class="explore">
		{#if step}
			{@const node = step.node}
			<header>
				<span class="mark" title={node.kind}>{MARK[node.kind]}</span>
				<h3>{printed(node.step)}</h3>
			</header>
			<div class="field"><span>kind</span><span>{node.kind}</span></div>
			<div class="field">
				<span>side</span><span>{printed(node.side)} · {program.sides[node.side]}</span>
			</div>
			<div class="field"><span>path</span><span class="path">{node.path}</span></div>
			{#if node.kind === 'roll'}
				<h2>target</h2>
				<Readings readings={[node.target]} width={STRIP} />
				<h2>modifiers</h2>
				{#if node.modifiers.length}
					{#each node.modifiers as modifier}
						<div class="field">
							<span>{named(modifier.rule)}</span><span class="num">{signed(modifier.move)}</span>
						</div>
					{/each}
				{:else}
					<span class="meta">none</span>
				{/if}
			{:else if node.kind === 'decision'}
				<h2>options</h2>
				{#each node.options as option}
					<div class="field"><span>{option}</span></div>
				{/each}
			{/if}
			<h2>edge out</h2>
			{#if node.edge.readings.length}
				<div class="readings">
					<Readings readings={node.edge.readings} width={STRIP} />
				</div>
			{:else}
				<span class="meta">no readings</span>
			{/if}
		{:else if block}
			<header>
				<span class="mark" title={block.block.kind}>{MARK.group}</span>
				<h3>{printed(last(block.path))}</h3>
			</header>
			<div class="field"><span>kind</span><span>{block.block.kind}</span></div>
			<div class="field"><span>steps</span><span class="num">{block.steps.length}</span></div>
			<div class="field"><span>path</span><span class="path">{block.path}</span></div>
			{#if block.block.kind === 'group'}
				<h2>multiplier</h2>
				<Readings readings={block.multiplier} width={STRIP} />
				<button class="btn btn-sm" onclick={() => toggle(block.path)}>
					{block.collapsed ? 'expand' : 'collapse'}
				</button>
			{/if}
		{:else if rule}
			<header>
				<h3>{rule.name}</h3>
			</header>
			<div class="field"><span>bearer</span><span>{bearer(rule.bearer)}</span></div>
			<div class="field"><span>id</span><span class="path">{rule.rule}</span></div>
			<h2>landings</h2>
			{#each rule.landings as landing}
				<div class="field">
					<span>{printed(last(landing.at))}</span>
					<span class="verdict {landing.verdict}">{landing.verdict}</span>
				</div>
			{/each}
		{:else}
			<span class="meta">select a step, group or rule to explore it</span>
		{/if}
	</aside>
</div>

<style>
	.shell {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 272px;
		height: calc(100vh - 2.4rem - 3rem);
	}

	.stage {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}

	.head {
		display: flex;
		align-items: baseline;
		gap: var(--space-5);
		padding: 0 var(--space-3) var(--space-2);
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
		flex: 1;
		min-height: 0;
		display: grid;
		align-content: center;
		justify-content: start;
		overflow: auto;
		padding: 0 var(--space-3);
		background: var(--sunken);
		border-top: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
	}

	.canvas {
		position: relative;
		user-select: none;
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

	.frame.on {
		stroke: var(--accent);
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

	.landing.on {
		stroke: var(--accent);
	}

	.card,
	.frame-head {
		position: absolute;
		display: flex;
		flex-direction: column;
		gap: 2px;
		cursor: grab;
		touch-action: none;
	}

	.card.held,
	.frame-head.held {
		cursor: grabbing;
	}

	.card {
		padding: var(--space-1) var(--space-2);
		background: var(--panel);
		border: 1px solid var(--line);
		border-left-width: 3px;
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.card.on {
		border-color: var(--accent);
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
		justify-content: center;
	}

	.card header,
	.frame-head {
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}

	.frame-head {
		padding: 0 var(--space-2);
	}

	.card h3,
	.frame-head h3 {
		font-size: var(--text-sm);
		line-height: 1.2;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.card header h3 {
		white-space: normal;
	}

	.frame-head h3,
	.card.rule h3 {
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

	.side {
		font-size: var(--text-xs);
		color: var(--dim);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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

	.caption {
		position: absolute;
		transform: translate(-50%, calc(-100% - 3px));
		font: 10px / 1.4 var(--font-mono);
		color: var(--dim);
		white-space: nowrap;
		pointer-events: none;
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
		pointer-events: none;
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
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
		white-space: nowrap;
		overflow: hidden;
	}

	.unmodelled .legend,
	.explore .verdict {
		position: static;
		transform: none;
	}

	.explore {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-height: 0;
		overflow-y: auto;
		padding: 0 var(--space-3);
		border-left: 1px solid var(--line);
	}

	.explore header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding-bottom: var(--space-1);
	}

	.explore h2 {
		margin-top: var(--space-3);
	}

	.explore .field span:first-child {
		color: var(--dim);
	}

	.explore .field span:last-child {
		color: var(--ink);
		text-align: right;
	}

	.explore .field .path {
		font: var(--text-xs) / 1.6 var(--font-mono);
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.explore .readings {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.explore .btn {
		align-self: flex-start;
		margin-top: var(--space-2);
	}
</style>
