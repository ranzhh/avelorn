<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { ChargeArc, FightBody, FightLanes } from '$lib/api/client';
	import type { Placed as Block } from '$lib/table';
	import Battlefield from './Battlefield.svelte';
	import Drawn from './Drawn.svelte';
	import type { Field } from './field';
	import { INSET } from './faces';
	import { draw, type Lane, type Placed } from './layout';
	import { measurer } from './measure';
	import type { View } from './odds';

	type Reacting = NonNullable<FightBody['charge']>['reaction'];

	interface Props {
		lanes: FightLanes;
		view: View;
		/** The charge as last asked for, which the battlefield's inputs show while a redraw is on its way. */
		charge: NonNullable<FightBody['charge']> | null;
		/** The blocks the battlefield measures, where the table placed them. */
		field: Field | null;
		/** The node showing its whole face, if any. */
		open: string | null;
		/** The unit edited in place, if any, and the controls that edit it. */
		editing: Lane | null;
		editor: Snippet<[Lane]>;
		ontoggle: (id: string) => void;
		/** A unit double-clicked: edit it. */
		onedit: (lane: Lane) => void;
		oncharge: (change: { full_inches?: number; arc?: ChargeArc; reaction?: Reacting }) => void;
		/** A block dragged across the battlefield's crop. */
		onmove: (lane: Lane, block: Block) => void;
	}

	let {
		lanes,
		view,
		charge,
		field,
		open,
		editing,
		editor,
		ontoggle,
		onedit,
		oncharge,
		onmove
	}: Props = $props();

	const measure = measurer();

	let editorHeight = $state(160);
	const drawing = $derived(
		draw(lanes, measure, open, editing && { lane: editing, height: editorHeight }, !!field, view)
	);

	$effect(() => {
		if (open && !drawing.nodes.some((node) => node.id === open)) ontoggle(open);
	});
	const REACTIONS = [
		{ offered: 'hold', value: 'hold', text: 'Hold', name: 'Hold' },
		{ offered: 'stand_and_shoot', value: 'stand-and-shoot', text: 'S&S', name: 'Stand & Shoot' },
		{ offered: 'flee', value: null, text: 'Flee', name: 'Flee' }
	] as const;
</script>

<Drawn
	{drawing}
	label="{lanes.units.attacker.name} against {lanes.units.target.name}"
	{open}
	{ontoggle}
	{onedit}
>
	{#snippet extra(node: Placed)}
		{@const { x, y, width, height } = node.box}
		{#if node.kind === 'unit' && node.face.slot}
			{@const slot = node.face.slot}
			<foreignObject x={x + slot.x} y={y + slot.y} width={slot.width} height={slot.height}>
				<div class="editor" bind:offsetHeight={editorHeight}>{@render editor(node.lane)}</div>
			</foreignObject>
		{:else if node.kind === 'battlefield' && charge}
			<Battlefield box={node.box} {charge} {field} open={open === node.id} {oncharge} {onmove} />
		{:else if node.kind === 'reaction' && lanes.reaction}
			{@const reaction = lanes.reaction}
			<rect class="card" {x} {y} {width} {height} rx="8" />
			<rect class="spine" {x} {y} width="4" {height} />
			<text class="title" x={x + INSET} y={y + 23}>Reaction</text>
			<foreignObject x={x + INSET} y={y + 36} width={width - INSET - 8} height="28">
				<div class="segments" role="radiogroup" aria-label="reaction">
					{#each REACTIONS as choice}
						<button
							role="radio"
							aria-checked={reaction.chosen === choice.value}
							title={choice.name}
							class:on={reaction.chosen === choice.value}
							disabled={!reaction.offered[choice.offered] || choice.value === null}
							onclick={() => choice.value && oncharge({ reaction: choice.value })}
							>{choice.text}</button
						>
					{/each}
				</div>
			</foreignObject>
		{/if}
	{/snippet}
</Drawn>

<style>
	text {
		fill: var(--ink);
	}
	.title {
		font-weight: 600;
	}
	.card {
		fill: var(--panel);
		stroke: #bdbdbd;
	}
	.spine {
		fill: var(--target);
	}
	.editor {
		display: grid;
		gap: var(--space-2);
		cursor: auto;
	}
	.segments {
		display: flex;
		gap: 2px;
	}
	.segments button {
		height: 26px;
		padding: 0 0.6rem;
		font-size: 12px;
		cursor: pointer;
	}
	.segments button.on {
		color: var(--on-accent);
		background: var(--target);
		border-color: var(--target);
	}
	.segments button:disabled {
		color: #b0b0b0;
		background: #f4f4f4;
		border-color: #d6d6d6;
		cursor: default;
	}
</style>
