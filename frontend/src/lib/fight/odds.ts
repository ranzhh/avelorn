import type { FightLanes } from '$lib/api/client';
import type { Lane, Share } from './faces';

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
 * The chances given each node is reached: a Break test's outcomes over taking
 * it, the result over the round fought.
 */
export function odds(lanes: FightLanes): Odds {
	const { breaks, result } = lanes;
	const outcomes = (lane: Lane): [string, number][] => {
		const test = breaks[lane];
		const over = test.taken && 1 / test.taken;
		return OUTCOMES.map(([name, key]) => [name, over * test[key]]);
	};
	return {
		taken: { attacker: breaks.attacker.taken, target: breaks.target.taken },
		outcomes: { attacker: outcomes('attacker'), target: outcomes('target') },
		shares: [
			['attacker', result.attacker_wins],
			['draw', result.draw],
			['target', result.target_wins]
		]
	};
}
