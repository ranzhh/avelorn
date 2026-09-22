<script lang="ts">
	import Readings from './Readings.svelte';
	import { FRAME, MARGIN, caption, fitted, layout, moved, type Moves, type Point } from './layout';
	import type { Program, Side, StepKind, Verdict } from '$lib/graph/types';

	let { program }: { program: Program } = $props();

	let folded = $state<Record<string, boolean>>({});
	const collapsed = $derived(
		program.blocks
			.filter(
				(block) =>
					(block.kind === 'sequence' || block.kind === 'repeat') &&
					(folded[block.path] ?? block.collapsed)
			)
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
					<span class="who {side}"><i></i>{program.sides[side]}</span>
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
							<span class="side">{each.summary}</span>
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
							{#if each.block.kind === 'repeat'}
								<span class="side">× {caption(each.multiplier)}</span>
							{/if}
							<button class="btn btn-ghost btn-sm fold" onclick={() => toggle(each.path)}>
								collapse
							</button>
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
				<span>side</span><span>{program.sides[node.side]}</span>
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
			{#if block.block.kind === 'repeat'}
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
		grid-template-columns: minmax(0, 1fr) 15rem;
		min-height: 32rem;
		border: 1px solid #bbb;
	}
	.stage {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.head,
	.unmodelled {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 0.6rem;
		border-bottom: 1px solid #bbb;
	}
	.cluster,
	.who,
	.legend > span {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.legend {
		margin-left: auto;
		font-size: 0.75rem;
	}
	.who i,
	.mark {
		display: inline-grid;
		place-items: center;
		width: 1.1rem;
		height: 1.1rem;
		border: 1px solid #555;
		font-size: 0.65rem;
		font-style: normal;
	}
	.this-model i {
		background: #dcecff;
	}
	.the-enemy i {
		background: #ffe0dc;
	}
	.scroll {
		flex: 1;
		overflow: auto;
		padding: 1rem;
		background: #fafafa;
	}
	.canvas {
		position: relative;
	}
	svg {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	marker path {
		fill: #555;
	}
	.frame {
		fill: #f5f5f5;
		stroke: #999;
		stroke-dasharray: 4 3;
	}
	.edge,
	.landing {
		stroke: #555;
		stroke-width: 1;
	}
	.edge.times {
		stroke-dasharray: 4 3;
	}
	.card,
	.frame-head {
		position: absolute;
		padding: 0.35rem;
		border: 1px solid #777;
		background: #fff;
		cursor: grab;
		overflow: hidden;
	}
	.card header,
	.frame-head {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	.card.this-model {
		border-left: 3px solid #3677b8;
	}
	.card.the-enemy {
		border-left: 3px solid #b84a3d;
	}
	.card.rule {
		background: #f5f5f5;
	}
	.card.on,
	.frame.on {
		outline: 2px solid #111;
	}
	.caption,
	.verdict {
		position: absolute;
		transform: translate(-50%, -50%);
		padding: 0 0.2rem;
		background: #fff;
		font:
			0.7rem ui-monospace,
			monospace;
	}
	.fold {
		margin-left: auto;
	}
	.explore {
		padding: 0.75rem;
		border-left: 1px solid #bbb;
	}
	.explore > * + * {
		margin-top: 0.5rem;
	}
</style>
