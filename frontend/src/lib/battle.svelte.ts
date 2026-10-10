import type { FightBody, FightReport, VolleyBody, VolleyReport } from './api/client';
import type { Placed } from './table';

/** What the table last resolved: the action, the body it posted, and the report it got back. */
export type Resolution =
	| { action: 'fight'; body: FightBody; report: FightReport }
	| { action: 'volley'; body: VolleyBody; report: VolleyReport };

/** The battle table as the user is building it, outliving any one page. */
class Battle {
	placed = $state<Placed[]>([]);
	nextId = $state(1);
	stamped = $state(0);
	/** The pair a menu is open on: what the first could do to the second. */
	asking = $state<{ mover: number; target: number } | null>(null);
	resolved = $state<Resolution | null>(null);
}

export const battle = new Battle();
