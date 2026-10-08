"use strict";

const dialog = document.getElementById("day-dialog");
const content = document.getElementById("dialog-content");
let pendingRequest = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderAppointments(appointments) {
  if (!appointments.length) {
    const state = element("div", "empty-state");
    state.append(
      element("strong", "", "Nenhum agendamento neste dia"),
      element("p", "", "Quando houver consultas, elas aparecerão aqui."),
    );
    content.replaceChildren(state);
    return;
  }
  const list = element("ul", "appointment-list");
  for (const appointment of appointments) {
    const item = element("li", "appointment");
    const details = element("div", "appointment-details");
    details.append(
      element("p", "appointment-name", appointment.cliente),
      element(
        "p",
        "appointment-kind",
        appointment.nutricionista || "Consulta nutricional",
      ),
    );
    if (appointment.detalhes_url) {
      const link = element(
        "a",
        "appointment-link",
        "Ver informações do paciente",
      );
      link.href = appointment.detalhes_url;
      details.append(link);
    }
    const status = [
      "confirmado",
      "pendente",
      "cancelado",
      "concluido",
    ].includes(appointment.status)
      ? appointment.status
      : "pendente";
    item.append(
      element("span", "appointment-time", appointment.horario),
      details,
      element("span", `appointment-status ${status}`, appointment.status_label),
    );
    list.append(item);
  }
  content.replaceChildren(list);
}

async function openDay(button) {
  if (pendingRequest) pendingRequest.abort();
  const controller = new AbortController();
  pendingRequest = controller;
  const dateString = button.dataset.date;
  // Build a local date explicitly: parsing YYYY-MM-DD as UTC can shift the day.
  const [year, month, day] = dateString.split("-").map(Number);
  const date = new Date(year, month - 1, day, 12);
  document.getElementById("dialog-title").textContent = date.toLocaleDateString(
    "pt-BR",
    {
      day: "numeric",
      month: "long",
      year: "numeric",
    },
  );
  document.getElementById("dialog-weekday").textContent =
    date.toLocaleDateString("pt-BR", {
      weekday: "long",
    });
  content.replaceChildren(
    element("p", "loading-state", "Carregando agendamentos…"),
  );
  content.setAttribute("aria-busy", "true");
  if (!dialog.open) dialog.showModal();

  try {
    const url = new URL(dialog.dataset.endpoint, window.location.origin);
    url.searchParams.set("data", dateString);
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.redirected)
      throw new Error(
        "Sua sessão expirou. Atualize a página para entrar novamente.",
      );
    if (!response.ok)
      throw new Error(
        "Não foi possível carregar os agendamentos. Feche e tente novamente.",
      );
    const data = await response.json();
    if (!Array.isArray(data.agendamentos))
      throw new Error("Resposta inválida. Feche e tente novamente.");
    if (!controller.signal.aborted) renderAppointments(data.agendamentos);
  } catch (error) {
    if (!controller.signal.aborted) {
      const message =
        error instanceof TypeError
          ? "Não foi possível conectar. Verifique sua conexão e tente novamente."
          : error.message;
      content.replaceChildren(element("p", "error-message", message));
    }
  } finally {
    if (pendingRequest === controller) {
      content.removeAttribute("aria-busy");
      pendingRequest = null;
    }
  }
}

document.querySelectorAll(".day-button").forEach((button) => {
  button.addEventListener("click", () => openDay(button));
});
document
  .getElementById("close-dialog")
  .addEventListener("click", () => dialog.close());
document
  .getElementById("done-dialog")
  .addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  const bounds = dialog.getBoundingClientRect();
  if (
    event.target === dialog &&
    (event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom)
  )
    dialog.close();
});
dialog.addEventListener("close", () => {
  if (pendingRequest) pendingRequest.abort();
  pendingRequest = null;
  content.removeAttribute("aria-busy");
});
