/**
 * The facts about a shot that the table cannot see.
 *
 * The geometry answers range and arc. It does not answer whether the shooter
 * moved this turn, whether the target is behind a hedge, or how many models
 * the target started the battle with. Those are held here and sent with every
 * volley, so a number on screen is the number for the situation being asked
 * about rather than for a clean one.
 */

export interface Conditions {
	/** Whether the shooter moved in its Movement phase. Gates Moving and Shooting. */
	moved: boolean;
	/** Cover and target size, in the printed convention: a penalty is negative. */
	hit: number;
	/**
	 * The target's model count at the start of the battle, or null for a unit
	 * that has taken no casualties. Governs the Fall Back or Flee split.
	 */
	battleStrength: number | null;
}

export const FRESH: Conditions = { moved: false, hit: 0, battleStrength: null };

/** The furthest the situational stepper goes each way. */
export const RANGE = { least: -3, most: 1 } as const;

export function stepped(hit: number, by: number): number {
	return Math.min(RANGE.most, Math.max(RANGE.least, hit + by));
}

/**
 * The battle strength to send for a target of this size.
 *
 * A count below the target's current size is impossible -- a unit cannot have
 * started the battle smaller than it stands now -- and the API refuses it, so
 * it is clamped up here rather than sent to be rejected. Null is the default
 * the engine reads as "no casualties yet".
 */
export function strengthFor(held: number | null, size: number): number | null {
	if (held === null) return null;
	return Math.max(held, size);
}

/** What the header row shows while the dock is shut. */
export function summary(conditions: Conditions): string {
	const said = [
		conditions.moved ? 'moved' : '',
		conditions.hit ? `${conditions.hit > 0 ? '+' : ''}${conditions.hit} to hit` : '',
		conditions.battleStrength === null ? '' : `from ${conditions.battleStrength}`
	].filter(Boolean);
	return said.join(' · ');
}
