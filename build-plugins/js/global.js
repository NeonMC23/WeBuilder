/* WeBuilder global runtime v1.2.0 */
(() => {
  const callbacks = [];
  let ready = document.readyState !== 'loading';

  window.WeBuilder = {
    version: "1.2.0",
    ready(callback) {
      if (ready) callback();
      else callbacks.push(callback);
    },
    registerInitializer(callback) { this.ready(callback); }
  };

  if (!ready) {
    document.addEventListener('DOMContentLoaded', () => {
      ready = true;
      callbacks.splice(0).forEach((callback) => callback());
      document.dispatchEvent(new CustomEvent('webuilder:ready'));
    }, { once: true });
  } else {
    queueMicrotask(() => document.dispatchEvent(new CustomEvent('webuilder:ready')));
  }
})();
