document.querySelectorAll("form[data-single-submit]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    form.querySelectorAll('[type="submit"]').forEach((button) => {
      button.disabled = true;
      button.textContent = "Salvando…";
    });
  });
});

document.querySelector("[data-copy-password]")?.addEventListener("click", async () => {
  const status = document.querySelector("#copy-status");
  try {
    await navigator.clipboard.writeText(document.querySelector("#temporary-password").textContent);
    status.textContent = "Senha copiada.";
  } catch {
    status.textContent = "Não foi possível copiar automaticamente. Selecione a senha e copie manualmente.";
  }
});
