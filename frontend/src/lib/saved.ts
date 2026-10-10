import { entry } from './corpus';
import { byName } from './options';
import type { ChosenOption, MusteredUnit } from './api/client';

/** A block as the browser saved it; a list saved before options had ids names them. */
export type Saved = Omit<MusteredUnit, 'options'> & { options: (string | ChosenOption)[] };

/** A saved list read back, and the saved blocks no datasheet could be read for. */
export interface ReadBack {
	blocks: MusteredUnit[];
	unread: Saved[];
}

async function readOne(block: Saved): Promise<MusteredUnit | null> {
	const names = block.options.filter((option) => typeof option === 'string');
	const kept = block.options.filter((option) => typeof option !== 'string');
	if (!names.length) return { ...block, options: kept };
	const sheet = await entry('unit', block.unit).catch(() => null);
	if (!sheet) return null;
	return { ...block, options: byName(sheet.options ?? [], names) };
}

/**
 * Read a saved list back, an older block's option names turned into the ids they bought.
 *
 * Each block is read on its own, so one whose datasheet cannot be read is set
 * aside without taking the rest of the list with it.
 */
export async function readBack(saved: Saved[]): Promise<ReadBack> {
	const read = await Promise.all(saved.map(readOne));
	return {
		blocks: read.filter((block) => block !== null),
		unread: saved.filter((_, at) => read[at] === null)
	};
}
