/* WeBuilder component: alert */
window.WeBuilder.ready(() => {
  document.querySelectorAll('.wb-alert__close').forEach((button) => button.addEventListener('click', () => button.closest('.wb-alert')?.remove()));
});
