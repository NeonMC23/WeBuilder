/* WeBuilder component: accordion */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.wb-accordion__item').forEach((item) => { const button = item.querySelector('button'); const panel = item.querySelector('.wb-accordion__panel'); button?.addEventListener('click', () => { const open = button.getAttribute('aria-expanded') === 'true'; button.setAttribute('aria-expanded', String(!open)); panel?.toggleAttribute('hidden', open); }); });
});
