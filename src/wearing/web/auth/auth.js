// Input state only. Never reads, stores, logs or transmits password text.
(() => {
  const start = () => {
    const password = document.querySelector('input[autocomplete="new-password"],input[autocomplete="current-password"],#password');
    document.querySelector('[data-password-toggle]')?.addEventListener('click', event => {
      if (!password) return;
      const visible = password.type === 'password';
      password.type = visible ? 'text' : 'password';
      event.currentTarget.textContent = visible ? '隐藏' : '显示';
      event.currentTarget.setAttribute('aria-pressed', String(visible));
    });
    document.querySelectorAll('form').forEach(form => {
      form.addEventListener('submit', event => {
        if (form.dataset.pending) { event.preventDefault(); return; }
        form.dataset.pending = 'true';
        const button = event.submitter;
        if (button && (button.classList.contains('primary') || button.id === 'kc-login')) {
          button.dataset.originalLabel = button.textContent;
          button.textContent = '正在确认…';
          button.setAttribute('aria-disabled', 'true');
        }
      });
    });
    window.addEventListener('pageshow', () => {
      document.querySelectorAll('form[data-pending]').forEach(form => delete form.dataset.pending);
      document.querySelectorAll('[data-original-label]').forEach(button => {
        button.textContent = button.dataset.originalLabel;
        button.removeAttribute('aria-disabled');
      });
    });
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start) : start();
})();
