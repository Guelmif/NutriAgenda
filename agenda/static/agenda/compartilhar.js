"use strict";
document.getElementById("copy-link")?.addEventListener("click", async () => {
  const input = document.getElementById("share-link");
  const feedback = document.getElementById("copy-feedback");
  try {
    await navigator.clipboard.writeText(input.value);
    feedback.textContent =
      "Link copiado. Você já pode compartilhar com o paciente.";
  } catch {
    input.select();
    feedback.textContent = "Selecione e copie o link acima.";
  }
});
