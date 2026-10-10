<script lang="ts">
	import Readings from './Readings.svelte';
	import {
		FRAME,
		MARGIN,
		applied,
		caption,
		fitted,
		foldable,
		grants,
		landed,
		layout,
		moved,
		startsFolded,
		type Moves,
		type Point
	} from './layout';
	import type { Holder, Program, StepKind } from '$lib/graph/types';

	let { program }: { program: Program } = $props();

	let folded = $state<Record<string, boolean>>({});
	const collapsed = $derived(
		program.blocks
			.filter((block) => foldable(block) && (folded[block.path] ?? startsFolded(block)))
			.map((block) => block.path)
	);
	let moves = $state<Moves>({});
	let canvasWidth = $state(0);

	const metrics = $derived(fitted(program, collapsed, Math.max(canvasWidth - 2 * MARGIN, 1)));
	const drawn = $derived(moved(layout(program, collapsed, metrics), moves));

	type Pick = { kind: 'step' | 'block' | 'rule'; id: string };
	let selected = $state<Pick | null>(null);

	const node = $derived(
		selected?.kind === 'step' ? program.nodes.find((each) => each.path === selected!.id) : undefined
	);
	const block = $derived(
		selected?.kind === 'block' ? drawn.blocks.find((each) => each.path === selected!.id) : undefined
	);
	const rule = $derived(
		selected?.kind === 'rule' ? program.rules.find((each) => each.id === selected!.id) : undefined
	);

	const MARK: Record<StepKind | 'group', string> = {
		measurement: 'M',
		decision: 'D',
		roll: 'R',
		consequence: 'C',
		group: 'G'
	};
	const STRIP = 236;

	const printed = (slug: string) => slug.replaceAll('-', ' ');
	const last = (path: string) => path.slice(path.lastIndexOf('/') + 1);
	const within = (path: string) => path.slice(path.indexOf('/') + 1);
	const named = (id: string) => program.rules.find((each) => each.id === id)?.name ?? id;
	const held = (holder: Holder) => `${holder.part} (${holder.side})`;
	const tint = (side: string) => `side-${program.sides.indexOf(side)}`;
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

	function choose(kind: Pick['kind'], id: string) {
		selected = { kind, id };
	}
</script>

<div class="shell">
	<div class="stage">
		<div class="head">
			<h1>{program.program}</h1>
			<div class="cluster sides">
				{#each program.sides as side}
					<span class="who {tint(side)}"><i></i>{side}</span>
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
								<button class="fold" title="expand" onclick={() => toggle(each.path)}>▶</button>
								<span class="mark" title="group">{MARK.group}</span>
								<h3 title={printed(last(each.path))}>{printed(last(each.path))}</h3>
							</header>
							{#each each.summary as line (line.side)}
								<span class="line {tint(line.side)}" title={line.text}>{line.text}</span>
							{/each}
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
							{#if foldable(each.block)}
								<button class="fold" title="collapse" onclick={() => toggle(each.path)}>▼</button>
							{/if}
							<span class="mark" title={each.block.kind}>{MARK.group}</span>
							<h3>{printed(last(each.path))}</h3>
							{#if each.block.kind === 'repeat'}
								<span class="side">× {caption(each.multiplier)}</span>
							{/if}
						</div>
					{/if}
				{/each}

				{#each drawn.steps as placed (placed.path)}
					{@const node = placed.node}
					{@const pick = { kind: 'step', id: placed.path } as const}
					<div
						class="card {tint(node.side)}"
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

				{#each drawn.captions as each}
					<span class="caption" style="left: {each.at.x}px; top: {each.at.y}px">{each.text}</span>
				{/each}
			</div>
		</div>

		<footer class="unmodelled">
			<span class="eyebrow">not modelled</span>
			{#if drawn.unmodelled.length}
				{#each drawn.unmodelled as each, index (each.id)}
					<span>{index ? '· ' : ''}{each.name} <span class="meta">{held(each.holder)}</span></span>
				{/each}
			{:else}
				<span class="meta">none</span>
			{/if}
		</footer>
	</div>

	<aside class="explore">
		{#if node}
			<header>
				<span class="mark" title={node.kind}>{MARK[node.kind]}</span>
				<h3>{printed(node.step)}</h3>
			</header>
			<div class="field"><span>kind</span><span>{node.kind}</span></div>
			<div class="field">
				<span>side</span><span>{node.side}</span>
			</div>
			<div class="field"><span>path</span><span class="path">{node.path}</span></div>
			{#if node.kind === 'roll' && node.printed}
				<h2>printed</h2>
				<Readings readings={[node.printed]} width={STRIP} />
			{:else if node.kind === 'decision'}
				<h2>options</h2>
				{#each node.options as option}
					<div class="field"><span>{option}</span></div>
				{/each}
			{/if}
			<h2>changes</h2>
			{#if node.changes.length}
				{#each node.changes as change}
					<div class="field">
						<span>{named(change.rule)}</span><span class="num">{change.text}</span>
					</div>
				{/each}
			{:else}
				<span class="meta">none</span>
			{/if}
			<h2>rules</h2>
			{#each landed(program, node.path) as each (each.rule.id)}
				<div class="ruled">
					<input type="checkbox" checked={each.applied} disabled aria-label={each.rule.name} />
					<button
						class="link"
						title={held(each.rule.holder)}
						onclick={() => choose('rule', each.rule.id)}>{each.rule.name}</button
					>
				</div>
			{:else}
				<span class="meta">none</span>
			{/each}
			{#if node.kind === 'roll'}
				<h2>{node.printed ? 'in force' : 'target'}</h2>
				<Readings readings={[node.target]} width={STRIP} />
			{/if}
			<h2>edge out</h2>
			{#if !node.ran}
				<span class="meta">not run in this lane</span>
			{:else if node.edge.readings.length}
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
			{#if block.summary.length}
				<h2>readings</h2>
				{#each block.summary as line (line.side)}
					<p class="line {tint(line.side)}">{line.text}</p>
				{/each}
			{/if}
			{#if block.block.kind === 'repeat'}
				<h2>multiplier</h2>
				<Readings readings={block.multiplier} width={STRIP} />
			{/if}
			{#if foldable(block.block)}
				<button class="btn btn-sm" onclick={() => toggle(block.path)}>
					{block.collapsed ? 'expand' : 'collapse'}
				</button>
			{/if}
		{:else if rule}
			{@const granted = grants(program, rule)}
			<header>
				<h3>{rule.name}</h3>
			</header>
			<div class="field"><span>holder</span><span>{held(rule.holder)}</span></div>
			<div class="field"><span>id</span><span class="path">{rule.id}</span></div>
			<h2>lands on</h2>
			{#each rule.landings as landing (landing.at)}
				<div class="ruled">
					<input
						type="checkbox"
						checked={applied(landing.verdicts)}
						disabled
						aria-label={within(landing.at)}
					/>
					<button class="link path" onclick={() => choose('step', landing.at)}
						>{within(landing.at)}</button
					>
				</div>
			{:else}
				<span class="meta">none</span>
			{/each}
			{#if granted.length}
				<h2>grants</h2>
				{#each granted as each (each.id)}
					<div class="field"><span>{each.name}</span><span>{held(each.holder)}</span></div>
				{/each}
			{/if}
		{:else}
			<span class="meta">select a step or group to explore it</span>
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
	.side-0 i {
		background: #dcecff;
	}
	.side-1 i {
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
	.edge {
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
	.card.side-0 {
		border-left: 3px solid #3677b8;
	}
	.card.side-1 {
		border-left: 3px solid #b84a3d;
	}
	.card.on,
	.frame.on {
		outline: 2px solid #111;
	}
	.caption {
		position: absolute;
		transform: translate(-50%, -50%);
		padding: 0 0.2rem;
		background: #fff;
		font:
			0.7rem ui-monospace,
			monospace;
	}
	.card.group h3 {
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.line {
		display: block;
		padding-left: 0.3rem;
		overflow: hidden;
		color: var(--dim);
		white-space: nowrap;
		text-overflow: ellipsis;
		font:
			0.7rem ui-monospace,
			monospace;
	}
	.line.side-0 {
		border-left: 2px solid #3677b8;
	}
	.line.side-1 {
		border-left: 2px solid #b84a3d;
	}
	.fold {
		display: inline-grid;
		flex: none;
		place-items: center;
		width: 1.1rem;
		height: 1.1rem;
		padding: 0;
		border: 0;
		background: transparent;
		font-size: 0.65rem;
		cursor: pointer;
	}
	.explore {
		padding: 0.75rem;
		border-left: 1px solid #bbb;
	}
	.explore .line {
		white-space: normal;
	}
	.explore > * + * {
		margin-top: 0.5rem;
	}
	.ruled {
		display: flex;
		align-items: baseline;
		gap: 0.4rem;
	}
	.ruled .link {
		min-width: 0;
		padding: 0;
		text-align: left;
		overflow-wrap: anywhere;
	}
</style>
