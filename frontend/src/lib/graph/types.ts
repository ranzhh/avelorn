export type StepKind = 'measurement' | 'decision' | 'roll' | 'consequence';

export type Verdict = 'applied' | 'honoured' | 'held' | 'inapplicable';

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

export interface Modifier {
	rule: string;
	move: number;
}

interface Step {
	path: string;
	step: string;
	side: string;
	inputs: string[];
	ran: boolean;
	edge: Edge;
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
	modifiers: Modifier[];
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

export interface Landing {
	at: string;
	verdicts: Judged[];
}

export interface Rule {
	rule: string;
	name: string;
	bearer: 'this-model' | 'the-enemy' | 'core';
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
