/* WeBuilder component: commerce:quantity */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.commerce-quantity').forEach((root) => { const input = root.querySelector('input'); root.querySelectorAll('[data-step]').forEach((button) => button.addEventListener('click', () => { const next = Math.min(Number(input.max), Math.max(Number(input.min), Number(input.value) + Number(button.dataset.step))); input.value = String(next); input.dispatchEvent(new Event('change', { bubbles: true })); })); });
});
