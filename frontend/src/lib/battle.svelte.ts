import type { FightBody, FightReport, VolleyBody, VolleyReport } from './api/client';
import type { Placed } from './table';

/** What the table last resolved: the action, between which blocks, the body and the report. */
export type Resolution =
	| { action: 'fight'; between: [number, number]; body: FightBody; report: FightReport }
	| { action: 'volley'; between: [number, number]; body: VolleyBody; report: VolleyReport };

/** The battle table as the user is building it, outliving any one page. */
class Battle {
	placed = $state<Placed[]>([]);
	nextId = $state(1);
	stamped = $state(0);
	/** The pair a menu is open on: what the first could do to the second. */
	asking = $state<{ mover: number; target: number } | null>(null);
	resolved = $state<Resolution | null>(null);

	/** Change a standing block, dropping the resolution it took part in if anything changed. */
	amend(id: number, change: Partial<Placed>) {
		const standing = this.placed.find((each) => each.id === id);
		if (!standing) return;
		this.placed = this.placed.map((each) => (each.id === id ? { ...standing, ...change } : each));
		const changed = Object.entries(change).some(
			([key, value]) => standing[key as keyof Placed] !== value
		);
		if (changed) this.unsettle(id);
	}

	/** Take a block off the table, and the resolution it took part in with it. */
	remove(id: number) {
		this.placed = this.placed.filter((each) => each.id !== id);
		this.unsettle(id);
	}

	private unsettle(id: number) {
		if (this.resolved?.between.includes(id)) this.resolved = null;
	}
}

export const battle = new Battle();
