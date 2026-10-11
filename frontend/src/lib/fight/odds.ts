import type { FightLanes } from '$lib/api/client';
import type { Lane, Share } from './faces';

/** Each chance conditional on reaching the node before it, or marginal over the whole charge. */
export type View = 'conditional' | 'marginal';
export const VIEWS: View[] = ['conditional', 'marginal'];

const OUTCOMES = [
	['Give Ground', 'give_ground'],
	['Fall Back in Good Order', 'fall_back_in_good_order'],
	['Break', 'break']
] as const;

/** The chances printed on the edges into the Break tests, on their outcomes and on the result. */
export interface Odds {
	taken: Record<Lane, number>;
	outcomes: Record<Lane, [string, number][]>;
	shares: Share[];
}

/**
 * The chances in one view. Conditional, a Break test's outcomes are over taking it
 * and the result over the round fought; marginal, each is the chance from the
 * start, and the charge falling short takes its share of the result.
 */
export function odds(lanes: FightLanes, view: View): Odds {
	const reach = view === 'marginal' ? (lanes.charge?.reaches ?? 1) : 1;
	const { breaks, result } = lanes;
	const outcomes = (lane: Lane): [string, number][] => {
		const test = breaks[lane];
		const over = view === 'marginal' ? reach : test.taken && 1 / test.taken;
		return OUTCOMES.map(([name, key]) => [name, over * test[key]]);
	};
	const shares: Share[] = [
		['attacker', reach * result.attacker_wins],
		['draw', reach * result.draw],
		['target', reach * result.target_wins]
	];
	if (reach < 1) shares.push(['short', 1 - reach]);
	return {
		taken: { attacker: reach * breaks.attacker.taken, target: reach * breaks.target.taken },
		outcomes: { attacker: outcomes('attacker'), target: outcomes('target') },
		shares
	};
}
