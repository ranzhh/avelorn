/** Put the cursor in this field when f is pressed anywhere on the page but in another field. */
export function findable(node: HTMLInputElement) {
	function find(event: KeyboardEvent) {
		if (event.key !== 'f' || event.metaKey || event.ctrlKey || event.altKey) return;
		if (event.defaultPrevented) return;
		const focus = document.activeElement;
		if (
			focus instanceof HTMLInputElement ||
			focus instanceof HTMLSelectElement ||
			focus instanceof HTMLTextAreaElement
		)
			return;
		event.preventDefault();
		node.focus();
		node.select();
	}
	window.addEventListener('keydown', find);
	return { destroy: () => window.removeEventListener('keydown', find) };
}
