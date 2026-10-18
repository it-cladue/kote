/* Dinamik katalog soru editörü. Her form kendi DOM kapsamı içinde çalışır. */
(() => {
  "use strict";

  const presets = {
    personel: { key: "personel", label: "Personel", preset: "personel", type: "text", required: true, options: [] },
    uye_id: { key: "uye_id", label: "Üye ID", preset: "uye_id", type: "text", required: true, options: [] },
    ana_uye_id: { key: "ana_uye_id", label: "Ana Üye ID", preset: "ana_uye_id", type: "text", required: true, options: [] },
    lead_id: { key: "lead_id", label: "Lead ID", preset: "lead_id", type: "text", required: true, options: [] },
    tip: { key: "tip", label: "Tip", preset: "tip", type: "select", required: true, options: ["sessiz", "telesekreter"] }
  };
  const templates = {
    tek_uye: [presets.personel, presets.uye_id],
    ark_ana: [presets.personel, { ...presets.uye_id, label: "Arkadaş Üye ID" }, presets.ana_uye_id],
    ana_only: [presets.personel, presets.ana_uye_id],
    sessiz_tip: [presets.personel, presets.uye_id, presets.tip]
  };

  const copy = (value) => JSON.parse(JSON.stringify(value));
  const make = (tag, attributes = {}, text = "") => {
    const node = document.createElement(tag);
    Object.entries(attributes).forEach(([name, value]) => {
      if (name === "className") node.className = value;
      else if (name === "checked") node.checked = Boolean(value);
      else if (name === "value") node.value = value;
      else node.setAttribute(name, value);
    });
    if (text) node.textContent = text;
    return node;
  };

  function inputLabel(text, control) {
    const label = make("label");
    label.append(document.createTextNode(text));
    label.append(control);
    return label;
  }

  function questionNode(question) {
    const item = make("fieldset", { "data-question": "", className: "katalog-soru" });
    const legend = make("legend", {}, question.preset ? `Hazır soru: ${question.preset}` : "Özel soru");
    item.append(legend);

    const key = make("input", { type: "text", maxlength: "40", pattern: "[a-z][a-z0-9_]{0,39}", "data-question-key": "", value: question.key || "",
      "data-gecersiz": "Soru anahtarı küçük harfle başlamalı; yalnız küçük harf, rakam ve alt çizgi (en çok 40).", "data-bos": "Soru anahtarı zorunludur." });
    key.readOnly = Boolean(question.preset);
    item.append(inputLabel("Anahtar ", key));

    const preset = make("input", { type: "hidden", "data-question-preset": "", value: question.preset || "" });
    item.append(preset);

    const label = make("input", { type: "text", maxlength: "120", required: "", "data-question-label": "", value: question.label || "" });
    item.append(inputLabel("Etiket ", label));

    const type = make("select", { "data-question-type": "" });
    type.append(make("option", { value: "text" }, "Metin"));
    type.append(make("option", { value: "select" }, "Seçim"));
    type.value = question.type === "select" ? "select" : "text";
    item.append(inputLabel("Tür ", type));

    const required = make("input", { type: "checkbox", "data-question-required": "", checked: question.required !== false });
    item.append(inputLabel("Zorunlu ", required));

    const options = make("textarea", { rows: "3", maxlength: "2429", "data-question-options": "", placeholder: "Her satıra bir seçenek" });
    options.value = Array.isArray(question.options) ? question.options.join("\n") : "";
    const optionsLabel = inputLabel("Seçenekler (her satır bir değer) ", options);
    optionsLabel.dataset.questionOptionsLabel = "";
    item.append(optionsLabel);

    const controls = make("p");
    controls.append(
      make("button", { type: "button", className: "btn kucuk", "data-question-up": "" }, "Yukarı"),
      document.createTextNode(" "),
      make("button", { type: "button", className: "btn kucuk", "data-question-down": "" }, "Aşağı"),
      document.createTextNode(" "),
      make("button", { type: "button", className: "btn kucuk tehlike", "data-question-remove": "" }, "Sil")
    );
    item.append(controls);

    const refreshType = () => {
      const select = type.value === "select";
      options.disabled = !select;
      optionsLabel.hidden = !select;
    };
    type.addEventListener("change", refreshType);
    refreshType();
    return item;
  }

  function questionsFromDom(form) {
    const list = form.querySelector("[data-question-list]");
    if (!list) return [];
    return [...list.querySelectorAll("[data-question]")].map((item) => {
      const options = item.querySelector("[data-question-options]").value
        .split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      return {
        key: item.querySelector("[data-question-key]").value.trim().toLowerCase(),
        label: item.querySelector("[data-question-label]").value.trim(),
        preset: item.querySelector("[data-question-preset]").value,
        type: item.querySelector("[data-question-type]").value,
        required: item.querySelector("[data-question-required]").checked,
        options
      };
    });
  }

  function writeQuestions(form, questions) {
    const list = form.querySelector("[data-question-list]");
    if (!list) return;
    list.replaceChildren(...questions.map(questionNode));
  }

  function syncQuestions(form) {
    const hidden = form.querySelector("[data-questions-json]");
    if (hidden) hidden.value = JSON.stringify(questionsFromDom(form));
  }

  function addPreset(form) {
    const picker = form.querySelector("[data-preset-picker]");
    const preset = picker && presets[picker.value];
    if (!preset) return;
    const existing = questionsFromDom(form).some((question) => question.preset === preset.preset);
    if (existing) {
      window.alert("Bu hazır soru zaten ekli.");
      return;
    }
    const questions = questionsFromDom(form);
    questions.push(copy(preset));
    writeQuestions(form, questions);
  }

  function addCustom(form) {
    const existing = questionsFromDom(form);
    let index = 1;
    while (existing.some((question) => question.key === `ozel_soru_${index}`)) index += 1;
    existing.push({ key: `ozel_soru_${index}`, label: "Özel soru", preset: "", type: "text", required: true, options: [] });
    writeQuestions(form, existing);
  }

  function installEditor(form) {
    const initial = (() => {
      try {
        const parsed = JSON.parse(form.dataset.initialQuestions || "[]");
        return Array.isArray(parsed) ? parsed : [];
      } catch (_) {
        return [];
      }
    })();
    writeQuestions(form, initial);

    const mode = form.querySelector("[data-mode-select]");
    if (mode) {
      mode.addEventListener("change", () => {
        if (!templates[mode.value]) return;
        const current = questionsFromDom(form);
        if (current.length && !window.confirm("Hazır şablon mevcut soru listesini değiştirir. Devam edilsin mi?")) {
          mode.value = "custom";
          return;
        }
        writeQuestions(form, copy(templates[mode.value]));
      });
    }
    form.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button || !form.contains(button)) return;
      if (button.matches("[data-add-preset]")) {
        event.preventDefault();
        addPreset(form);
      } else if (button.matches("[data-add-custom]")) {
        event.preventDefault();
        addCustom(form);
      } else if (button.matches("[data-question-remove], [data-question-up], [data-question-down]")) {
        event.preventDefault();
        const question = button.closest("[data-question]");
        if (!question) return;
        if (button.matches("[data-question-remove]")) question.remove();
        else if (button.matches("[data-question-up]") && question.previousElementSibling) question.previousElementSibling.before(question);
        else if (button.matches("[data-question-down]") && question.nextElementSibling) question.nextElementSibling.after(question);
      }
    });
    form.addEventListener("submit", () => syncQuestions(form));
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-category-form]").forEach(installEditor);
  });
})();
