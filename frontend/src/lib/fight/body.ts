import type { FightBody } from '$lib/api/client';
import type { Lane } from './layout';

export type Deployment = FightBody['a'];

/** The side of the body fighting from a lane: the charger's is the attacker's, side a's with no charge. */
export function seat(body: FightBody, lane: Lane): 'a' | 'b' {
	const charger = body.charge?.side ?? 'a';
	if (lane === 'attacker') return charger;
	return charger === 'a' ? 'b' : 'a';
}

/** The body with the unit fighting from a lane deployed afresh. */
export function redeployed(body: FightBody, lane: Lane, change: Partial<Deployment>): FightBody {
	const side = seat(body, lane);
	return { ...body, [side]: { ...body[side], ...change } };
}
