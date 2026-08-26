<script lang="ts">
	import { datasheet } from '$lib/datasheets';
	import { api, type MusteredUnit } from '$lib/api/client';

	interface Props {
		label: string;
		units: { id: string; name: string; points: number }[];
		roster: MusteredUnit[];
		block: MusteredUnit | null;
		onblock: (block: MusteredUnit | null) => void;
		weapon: string;
		onweapon: (weapon: string) => void;
		onbusy: (busy: boolean) => void;
	}

	let { label, units, roster, block, onblock, weapon, onweapon, onbusy }: Props = $props();

	let refusal = $state('');

	async function fromRoster(event: Event) {
		const at = (event.currentTarget as HTMLSelectElement).value;
		if (at === '') return;
		const picked = roster[Number(at)];
		onblock(picked);
		onweapon(picked.weapons.at(-1) ?? '');
	}

	async function fromCorpus(event: Event) {
		const slug = (event.currentTarget as HTMLSelectElement).value;
		refusal = '';
		if (!slug) {
			onblock(null);
			return;
		}
		onbusy(true);
		const sheet = await datasheet(slug);
		const size = sheet?.unit_size.min ?? 1;
		const { data: mustered, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit: slug, size, options: [] } }
		);
		onbusy(false);
		if (!mustered) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not deploy that';
			return;
		}
		onblock(mustered);
		onweapon(mustered.weapons.at(-1) ?? '');
	}

	async function resize(event: Event) {
		if (!block) return;
		const size = Number((event.currentTarget as HTMLInputElement).value);
		refusal = '';
		onbusy(true);
		const { data: mustered, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit: block.unit, size, options: block.options } }
		);
		onbusy(false);
		if (!mustered) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not deploy that';
			return;
		}
		onblock(mustered);
	}
</script>

<fieldset>
	<legend>{label}</legend>

	{#if roster.length}
		<label>
			From your list
			<select onchange={fromRoster}>
				<option value="">—</option>
				{#each roster as entry, at}
					<option value={at}>{entry.name} × {entry.size}</option>
				{/each}
			</select>
		</label>
	{/if}

	<label>
		Or any datasheet
		<select onchange={fromCorpus}>
			<option value="">—</option>
			{#each units as unit}
				<option value={unit.id}>{unit.name}</option>
			{/each}
		</select>
	</label>

	{#if block}
		<p class="chosen">{block.name} — {block.points} pts</p>
		<label>
			Models
			<input type="number" min="1" value={block.size} onchange={resize} />
		</label>
		<label>
			Weapon in hand
			<select value={weapon} onchange={(e) => onweapon(e.currentTarget.value)}>
				{#each block.weapons as name}
					<option value={name}>{name}</option>
				{/each}
			</select>
		</label>
	{/if}

	{#if refusal}<p class="refusal">{refusal}</p>{/if}
</fieldset>

<style>
	fieldset {
		border: 1px solid var(--rule);
		border-radius: 3px;
		padding: 1rem;
	}

	label {
		display: block;
		margin-bottom: 0.6rem;
	}

	select,
	input[type='number'] {
		font: inherit;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--rule);
		border-radius: 3px;
		background: white;
	}

	input[type='number'] {
		width: 5rem;
	}

	.chosen {
		font-weight: 700;
		margin: 0.5rem 0;
	}

	.refusal {
		color: #8a1c1c;
		font-size: 0.9rem;
	}
</style>
