<script lang="ts">
	import { datasheet } from '$lib/datasheets';
	import { cost, repeated } from '$lib/options';
	import { api, type MusteredUnit, type UnitOption } from '$lib/api/client';

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
	let offered = $state<UnitOption[]>([]);
	let chosen = $state<string[]>([]);
	// A pick is two round trips, and a fieldset that shows nothing meanwhile
	// reads as broken rather than busy.
	let deploying = $state(false);

	// The specialist a datasheet prints last, skipping anything with no Combat
	// profile: archers carry a Longbow after their hand weapon.
	const fighting = (block: MusteredUnit) =>
		block.weapons.filter((weapon) => weapon.fights).at(-1)?.name ?? '';

	async function deploy(slug: string, size: number, options: string[], rearm: boolean) {
		refusal = '';
		deploying = true;
		onbusy(true);
		const { data: mustered, error: refused } = await api(window.location.origin, fetch).POST(
			'/muster',
			{ body: { unit: slug, size, options } }
		);
		deploying = false;
		onbusy(false);
		if (!mustered) {
			refusal = typeof refused?.detail === 'string' ? refused.detail : 'could not deploy that';
			return;
		}
		onblock(mustered);
		chosen = mustered.options;
		if (rearm) onweapon(fighting(mustered));
	}

	async function fromRoster(event: Event) {
		const at = (event.currentTarget as HTMLSelectElement).value;
		if (at === '') return;
		// Re-mustered rather than used as saved: a list in localStorage was
		// written by whatever version of the block shape was current then, and an
		// entry from before this page existed carries no weapons to fight with.
		const picked = roster[Number(at)];
		offered = (await datasheet(picked.unit))?.options ?? [];
		await deploy(picked.unit, picked.size, picked.options, true);
	}

	async function fromCorpus(event: Event) {
		const slug = (event.currentTarget as HTMLSelectElement).value;
		refusal = '';
		chosen = [];
		offered = [];
		if (!slug) {
			onblock(null);
			return;
		}
		deploying = true;
		const sheet = await datasheet(slug);
		offered = sheet?.options ?? [];
		deploying = false;
		await deploy(slug, sheet?.unit_size.min ?? 1, [], true);
	}

	async function toggle(name: string, on: boolean) {
		if (!block) return;
		const options = on ? [...chosen, name] : chosen.filter((each) => each !== name);
		chosen = options;
		await deploy(block.unit, block.size, options, false);
	}

	async function resize(event: Event) {
		if (!block) return;
		const size = Number((event.currentTarget as HTMLInputElement).value);
		await deploy(block.unit, size, chosen, false);
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

	{#if deploying}<p class="meta">deploying…</p>{/if}

	{#if block}
		<p class="chosen">{block.name} — {block.points} pts</p>
		<label>
			Models
			<input type="number" min="1" value={block.size} onchange={resize} />
		</label>

		{#if offered.length}
			<fieldset class="options">
				<legend>Options</legend>
				{#each offered as option}
					<label class="option">
						<input
							type="checkbox"
							checked={chosen.includes(option.name)}
							onchange={(e) => toggle(option.name, e.currentTarget.checked)}
						/>
						{option.name}
						<span class="meta">{cost(option)}</span>
						{#if repeated(offered, option.name)}
							<span class="warn">name repeats; both are bought together</span>
						{/if}
					</label>
				{/each}
			</fieldset>
		{/if}
		<label>
			Weapon in hand
			<select value={weapon} onchange={(e) => onweapon(e.currentTarget.value)}>
				{#each block.weapons.filter((weapon) => weapon.fights) as weapon}
					<option value={weapon.name}>{weapon.name}</option>
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

	fieldset.options {
		margin: 0 0 0.6rem;
		padding: 0.5rem 0.75rem;

		legend {
			font-size: 0.8rem;
			color: var(--muted);
		}
	}

	.option {
		font-size: 0.9rem;
		margin-bottom: 0.2rem;
	}

	.meta {
		color: var(--muted);
		font-size: 0.85rem;
	}

	.warn {
		color: #8a5a00;
		font-size: 0.8rem;
	}
</style>
