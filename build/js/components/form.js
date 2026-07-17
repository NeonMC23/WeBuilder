/* WeBuilder component: form */
window.WeBuilder.ready(() => {
  // build.json: contact.html / component 1.0.1
  document.querySelectorAll('[data-wb-instance]').forEach((element) => {
    if (element.dataset.wbInstance === "contact-html--1-0-1--contact-form") {
      element.addEventListener("submit", (event) => {
        const el = event.currentTarget;
        event.preventDefault(); console.log('Form submitted', new FormData(el)); alert('Thank you. This demo form was submitted locally.');
      });
    }
  });
});
