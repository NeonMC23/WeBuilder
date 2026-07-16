/* WeBuilder component: neon:terminal */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.neon-terminal').forEach((terminal) => terminal.querySelector('button')?.addEventListener('click', async (event) => { const text = [...terminal.querySelectorAll('code')].map((line) => line.textContent).join('\n'); await navigator.clipboard.writeText(text); event.currentTarget.textContent = 'Copié !'; }));
});
