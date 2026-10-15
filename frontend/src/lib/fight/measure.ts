import type { Font, Measure } from './faces';

const FONTS: Record<Font, string> = {
	title: '600 13px system-ui, sans-serif',
	text: '13px system-ui, sans-serif',
	small: '11px system-ui, sans-serif',
	chip: '11px system-ui, sans-serif',
	mono: '12px ui-monospace, Menlo, Consolas, monospace'
};

/** Measure text as the browser draws it in the drawing's fonts. */
export function measurer(): Measure {
	const context = document.createElement('canvas').getContext('2d')!;
	return (text, font) => {
		context.font = FONTS[font];
		return Math.ceil(context.measureText(text).width);
	};
}
