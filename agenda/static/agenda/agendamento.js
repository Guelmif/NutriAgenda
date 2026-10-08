"use strict";
(() => {
  const form = document.getElementById("booking-form");
  if (!form) return;
  const professional = document.getElementById("id_profissional");
  const date = document.getElementById("id_data");
  const time = document.getElementById("id_horario");
  const feedback = document.getElementById("availability-feedback");
  const submit = document.getElementById("submit-booking");
  let dates = [];
  let request = null;

  function updateSubmit() {
    submit.disabled = !(professional.value && date.value && time.value);
  }

  function options(select, placeholder, values, selected = "") {
    select.replaceChildren(new Option(placeholder, ""));
    for (const value of values)
      select.add(new Option(value.rotulo || value, value.valor || value));
    select.value = selected;
    select.disabled = !values.length;
    updateSubmit();
  }

  function selectTimes(selected = "") {
    const entry = dates.find((item) => item.valor === date.value);
    options(
      time,
      entry ? "Selecione um horário" : "Selecione primeiro a data",
      entry?.horarios || [],
      selected,
    );
  }

  async function loadDates(restore = false) {
    if (request) request.abort();
    const controller = new AbortController();
    request = controller;
    const selectedDate = restore ? date.value : "";
    const selectedTime = restore ? time.value : "";
    dates = [];
    options(date, "Selecione primeiro o nutricionista", []);
    options(time, "Selecione primeiro a data", []);
    feedback.textContent = "";
    if (!professional.value) return;
    feedback.textContent = "Buscando horários disponíveis…";
    try {
      const url = new URL(form.dataset.endpoint, window.location.origin);
      url.searchParams.set("profissional", professional.value);
      const response = await fetch(url, {
        signal: controller.signal,
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok)
        throw new Error(
          "Não foi possível buscar os horários. Selecione o nutricionista novamente para tentar.",
        );
      const data = await response.json();
      if (!Array.isArray(data.datas))
        throw new Error(
          "Resposta inválida. Atualize a página e tente novamente.",
        );
      if (controller.signal.aborted) return;
      dates = data.datas;
      options(
        date,
        dates.length ? "Selecione uma data" : "Sem datas disponíveis",
        dates,
        selectedDate,
      );
      selectTimes(selectedTime);
      feedback.textContent = dates.length
        ? ""
        : "Este nutricionista não possui mais horários disponíveis. Atualize a página ou escolha outro.";
    } catch (error) {
      if (!controller.signal.aborted)
        feedback.textContent =
          error instanceof TypeError
            ? "Não foi possível conectar. Selecione o nutricionista novamente para tentar."
            : error.message;
    }
  }
  professional.addEventListener("change", () => loadDates());
  date.addEventListener("change", () => selectTimes());
  time.addEventListener("change", updateSubmit);
  loadDates(true);
  for (const [fieldId, containerId] of [
    ["id_tem_problemas_saude", "health-details"],
    ["id_usa_medicacoes", "medication-details"],
  ]) {
    const field = document.getElementById(fieldId);
    const container = document.getElementById(containerId);
    const update = () => {
      container.hidden = field.value !== "sim";
    };
    field.addEventListener("change", update);
    update();
  }
})();
