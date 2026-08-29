<script lang="ts">
	import { RANGE, stepped, type Conditions } from '$lib/conditions';

	interface Props {
		conditions: Conditions;
		/** The target's current size, which its battle strength cannot fall below. */
		size: number | null;
		onchange: (conditions: Conditions) => void;
	}

	let { conditions, size, onchange }: Props = $props();

	const signed = (n: number) => (n > 0 ? `+${n}` : `${n}`);

	function amend(change: Partial<Conditions>) {
		onchange({ ...conditions, ...change });
	}

	function depleted(event: Event) {
		const raw = (event.currentTarget as HTMLInputElement).value;
		amend({ battleStrength: raw === '' ? null : Number(raw) });
	}
</script>

<label class="check">
	<input
		type="checkbox"
		checked={conditions.moved}
		onchange={(event) => amend({ moved: event.currentTarget.checked })}
	/>
	shooter moved
</label>

<div class="field">
	<span>to hit</span>
	<span class="cluster step">
		<button
			class="btn btn-sm"
			disabled={conditions.hit <= RANGE.least}
			onclick={() => amend({ hit: stepped(conditions.hit, -1) })}
			aria-label="one harder"
		>
			−
		</button>
		<span class="num held" class:neg={conditions.hit < 0} class:pos={conditions.hit > 0}>
			{signed(conditions.hit)}
		</span>
		<button
			class="btn btn-sm"
			disabled={conditions.hit >= RANGE.most}
			onclick={() => amend({ hit: stepped(conditions.hit, 1) })}
			aria-label="one easier"
		>
			+
		</button>
	</span>
</div>

<label class="field">
	<span>battle strength</span>
	<input
		class="input"
		type="number"
		min={size ?? 1}
		placeholder={size === null ? 'fresh' : `${size}`}
		value={conditions.battleStrength ?? ''}
		oninput={depleted}
	/>
</label>

<style>
	.check {
		margin-bottom: var(--space-1);
	}

	.step {
		gap: var(--space-1);
	}

	.held {
		min-width: 1.6rem;
		text-align: center;
		font-size: var(--text-sm);
	}

	/* A scoped rule outranks the global .pos and .neg, so only an unset
	   modifier takes the plain colour. */
	.held:not(.pos, .neg) {
		color: var(--ink);
	}
</style>
