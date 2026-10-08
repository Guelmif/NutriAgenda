"use strict";
(() => {
  const editor = document.getElementById("question-editor");
  if (!editor) return;
  const list = document.getElementById("question-list");
  const total = document.getElementById("id_perguntas-TOTAL_FORMS");
  const add = document.getElementById("add-question");
  const template = document.getElementById("empty-question");
  const feedback = document.getElementById("questions-feedback");
  function setup(card) {
    const type = card.querySelector('[name$="-tipo"]');
    const options = card.querySelector(".question-options");
    const remove = card.querySelector('[name$="-DELETE"]');
    remove.parentElement.lastChild.textContent = " Remover pergunta";
    function update() {
      options.hidden = type.value !== "escolha";
      card.classList.toggle("question-removed", remove.checked);
      for (const field of card.querySelectorAll("input, select, textarea")) {
        if (field === remove || field.type === "hidden") continue;
        if (!field.dataset.required)
          field.dataset.required = field.required ? "yes" : "no";
        field.required = !remove.checked && field.dataset.required === "yes";
      }
    }
    type.addEventListener("change", update);
    remove.addEventListener("change", update);
    update();
  }
  list.querySelectorAll(".question-card").forEach(setup);
  add.addEventListener("click", () => {
    const index = Number(total.value);
    if (index >= 50) {
      feedback.textContent =
        "Limite de 50 perguntas. Salve as remoções antes de adicionar outras.";
      return;
    }
    const fragment = document.createElement("template");
    fragment.innerHTML = template.innerHTML.replaceAll(
      "__prefix__",
      String(index),
    );
    const card = fragment.content.querySelector(".question-card");
    card.querySelector('[name$="-ordem"]').value = index + 1;
    list.append(fragment.content);
    total.value = index + 1;
    setup(card);
    card.querySelector('[name$="-rotulo"]').focus();
    feedback.textContent =
      "Pergunta adicionada. Preencha e salve as alterações.";
  });
})();
