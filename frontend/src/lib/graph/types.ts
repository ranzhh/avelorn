export type StepKind = 'measurement' | 'decision' | 'roll' | 'consequence';

export type Verdict = 'applied' | 'cancelled' | 'honoured' | 'held' | 'inapplicable';

export interface Outcome {
	value: number | string;
	p: number;
}

export interface Distribution {
	label: string;
	outcomes: Outcome[];
}

export interface Scalar {
	label: string;
	value: number | string;
}

export type Reading = Distribution | Scalar;

export interface Edge {
	readings: Reading[];
}

export interface Change {
	rule: string;
	text: string;
}

interface Step {
	path: string;
	step: string;
	side: string;
	inputs: string[];
	ran: boolean;
	edge: Edge;
	changes: Change[];
}

export interface Measurement extends Step {
	kind: 'measurement';
}

export interface Decision extends Step {
	kind: 'decision';
	options: string[];
}

export interface Roll extends Step {
	kind: 'roll';
	target: Reading;
	printed: Reading | null;
}

export interface Consequence extends Step {
	kind: 'consequence';
}

export type Node = Measurement | Decision | Roll | Consequence;

export interface Sequence {
	path: string;
	kind: 'sequence';
	collapsed: boolean;
}

export interface Repeat {
	path: string;
	kind: 'repeat';
	times: string;
	collapsed: boolean;
}

export interface Slot {
	path: string;
	kind: 'slot';
	empty: boolean;
}

export interface Body {
	path: string;
	kind: 'body';
	decision: string;
}

export type Block = Sequence | Repeat | Slot | Body;

export interface Judged {
	verdict: Verdict;
	p: number;
}

export type Carrier = 'model' | 'weapon' | 'armour' | 'item' | 'effect' | 'core';

export interface Holder {
	side: string;
	part: string;
}

export interface Source {
	carrier: Carrier;
	item: string | null;
	profile: string | null;
	via: string | null;
}

export interface Landing {
	at: string;
	triggers: string[];
	verdicts: Judged[];
}

export interface Rule {
	id: string;
	rule: string;
	name: string;
	holder: Holder;
	may: boolean;
	sources: Source[];
	landings: Landing[];
}

export interface Lane {
	decision: string;
	outcome: string;
}

export interface Program {
	program: string;
	sides: string[];
	nodes: Node[];
	blocks: Block[];
	rules: Rule[];
	lanes: Lane[];
}
