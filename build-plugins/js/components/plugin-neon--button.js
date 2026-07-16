/* WeBuilder component: neon:button */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.neon-button').forEach((button) => button.addEventListener('click', () => { button.classList.remove('is-pulsing'); void button.offsetWidth; button.classList.add('is-pulsing'); }));

  // build.json: index.html / component 0.0.0.1.0.0
  document.querySelectorAll('[data-wb-instance]').forEach((element) => {
    if (element.dataset.wbInstance === "index-html--0-0-0-1-0-0--neon-action") {
      element.addEventListener("click", (event) => {
        const el = event.currentTarget;
        console.log('Composant du plugin neon', el);
      });
    }
  });
});
