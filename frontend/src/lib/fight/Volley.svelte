<script lang="ts">
	import type { VolleyBody, VolleyLanes } from '$lib/api/client';
	import type { Placed as Block } from '$lib/table';
	import Battlefield from './Battlefield.svelte';
	import Drawn from './Drawn.svelte';
	import Settings, { type Mode } from './Settings.svelte';
	import Unit from './Unit.svelte';
	import { aimed, reaimed } from './body';
	import { measured, type Control, type Field } from './field';
	import type { Lane, Placed } from './layout';
	import { measurer } from './measure';
	import type { View } from './odds';
	import { drawVolley } from './volley';

	interface Props {
		lanes: VolleyLanes;
		body: VolleyBody;
		/** Whether the drawing is older than the body: a redraw on its way, or the body refused. */
		stale: boolean;
		/** The blocks the table placed, which the battlefield measures; null with no table. */
		field: Field | null;
		onedit: (body: VolleyBody) => void;
		/** A block dragged across the battlefield's crop. */
		onmove: (lane: Lane, block: Block) => void;
		mode: Mode;
	}

	let { lanes, body, stale, field, onedit, onmove, mode = $bindable() }: Props = $props();

	let open = $state<string | null>(null);
	let editing = $state<Lane | null>(null);
	let view = $state<View>('conditional');
	let editorHeight = $state(160);

	const measure = measurer();
	const drawing = $derived(
		drawVolley(
			lanes,
			measure,
			open,
			editing && { lane: editing, height: editorHeight },
			!!field,
			view
		)
	);

	const rows = $derived<Control[]>([
		field
			? { kind: 'read', name: 'distance', value: `${measured(field.blocks).full_inches}in` }
			: { kind: 'inches', name: 'distance', value: body.distance },
		{ kind: 'read', name: 'range', value: lanes.battlefield.band },
		{ kind: 'toggle', name: 'moved', value: body.moved ?? false }
	]);

	function row(name: string, value: number | string | boolean) {
		if (name === 'distance') onedit({ ...body, distance: value as number });
		else onedit({ ...body, moved: value as boolean });
	}

	function toggle(id: string) {
		editing = null;
		open = open === id ? null : id;
	}

	function close() {
		editing = null;
		open = null;
	}
</script>

<svelte:window onkeydown={(event) => event.key === 'Escape' && close()} />

<div class="volley" class:stale>
	<Settings bind:mode bind:view from="the volley" />
	<div class="stage">
		<Drawn
			{drawing}
			label="{lanes.units.attacker.name} shoot {lanes.units.target.name}"
			{open}
			ontoggle={toggle}
			onedit={(lane) => {
				open = `unit:${lane}`;
				editing = lane;
			}}
		>
			{#snippet extra(node: Placed)}
				{@const { x, y } = node.box}
				{#if node.kind === 'unit' && node.face.slot}
					{@const slot = node.face.slot}
					{@const lane = node.lane}
					<foreignObject x={x + slot.x} y={y + slot.y} width={slot.width} height={slot.height}>
						<div class="editor" bind:offsetHeight={editorHeight}>
							{#key lane}
								<Unit
									deployment={body[aimed(lane)]}
									frontage={lanes.units[lane].frontage}
									phase={lane === 'attacker' ? 'missile' : 'melee'}
									onchange={(change) => onedit(reaimed(body, lane, change))}
								/>
							{/key}
						</div>
					</foreignObject>
				{:else if node.kind === 'battlefield'}
					<Battlefield
						box={node.box}
						{rows}
						{field}
						open={open === node.id}
						arcs={false}
						onrow={row}
						{onmove}
					/>
				{/if}
			{/snippet}
		</Drawn>
	</div>
</div>

<style>
	.volley {
		position: relative;
		min-height: 24rem;
		border: 1px solid var(--line);
	}
	.stage {
		overflow-x: auto;
	}
	.volley.stale .stage {
		opacity: 0.7;
		transition: opacity 0.2s 0.15s;
	}
	.editor {
		display: grid;
		gap: var(--space-2);
		cursor: auto;
	}
</style>
