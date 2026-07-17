/* WeBuilder component: commerce:cart-button */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.commerce-cart-button').forEach((button) => button.addEventListener('click', () => { button.classList.add('is-added'); const original = button.textContent; button.textContent = 'Added ✓'; button.dispatchEvent(new CustomEvent('cart:add', { bubbles: true, detail: { productId: button.dataset.productId } })); setTimeout(() => { button.classList.remove('is-added'); button.textContent = original; }, 1200); }));

  // build.json: index.html / component 0.0.0.1.1.0.1
  document.querySelectorAll('[data-wb-instance]').forEach((element) => {
    if (element.dataset.wbInstance === "index-html--0-0-0-1-1-0-1--component") {
      element.addEventListener("cart:add", (event) => {
        const el = event.currentTarget;
        console.log('Product added:', event.detail.productId);
      });
    }
  });
});
