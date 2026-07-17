/* WeBuilder component: button */
window.WeBuilder.ready(() => {
  // build.json: index.html / component 1.0
  document.querySelectorAll('[data-wb-instance]').forEach((element) => {
    if (element.dataset.wbInstance === "index-html--1-0--discover") {
      element.addEventListener("click", (event) => {
        const el = event.currentTarget;
        document.querySelector('[data-id=features]')?.scrollIntoView({ behavior: 'smooth' });
      });
    }
  });
});
