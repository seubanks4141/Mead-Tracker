(() => {
  "use strict";

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

  const themeKey = "mead-tracker-theme";
  const themeChoices = new Set(["system", "light", "dark"]);
  const themeMedia = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  const themeSelects = $$("[data-theme-select]");
  const themeIcons = $$("[data-theme-icon]");

  const applyTheme = (requestedChoice, { persist = true, announce = true } = {}) => {
    const choice = themeChoices.has(requestedChoice) ? requestedChoice : "system";
    const effective = choice === "system"
      ? (themeMedia && themeMedia.matches ? "dark" : "light")
      : choice;

    document.documentElement.dataset.themeChoice = choice;
    document.documentElement.dataset.theme = effective;
    themeSelects.forEach((select) => {
      select.value = choice;
    });
    themeIcons.forEach((icon) => {
      icon.textContent = choice === "light" ? "☀" : (choice === "dark" ? "☾" : "◐");
    });

    const themeColor = $('meta[name="theme-color"]');
    if (themeColor) {
      themeColor.setAttribute("content", effective === "dark" ? "#17120f" : "#2b1c14");
    }

    if (persist) {
      try {
        window.localStorage.setItem(themeKey, choice);
      } catch (_error) {
        // The visual choice still applies for this page when storage is blocked.
      }
    }

    if (announce) {
      window.dispatchEvent(new CustomEvent("meadtracker:themechange", {
        detail: { choice, effective },
      }));
    }
  };

  themeSelects.forEach((select) => {
    select.addEventListener("change", () => applyTheme(select.value));
  });

  applyTheme(document.documentElement.dataset.themeChoice || "system", {
    persist: false,
    announce: false,
  });

  const handleSystemThemeChange = () => {
    if (document.documentElement.dataset.themeChoice === "system") {
      applyTheme("system", { persist: false });
    }
  };

  if (themeMedia) {
    if (typeof themeMedia.addEventListener === "function") {
      themeMedia.addEventListener("change", handleSystemThemeChange);
    } else if (typeof themeMedia.addListener === "function") {
      themeMedia.addListener(handleSystemThemeChange);
    }
  }

  const accountMenus = $$("[data-account-menu]");
  const closeAccountMenus = (exceptMenu = null) => {
    accountMenus.forEach((menu) => {
      if (menu !== exceptMenu) menu.removeAttribute("open");
    });
  };

  const navToggle = $("[data-nav-toggle]");
  const primaryNav = $("[data-primary-nav]");
  const closeNavigation = () => {
    if (!navToggle || !primaryNav) return;
    navToggle.setAttribute("aria-expanded", "false");
    primaryNav.dataset.open = "false";
  };

  if (navToggle && primaryNav) {
    navToggle.addEventListener("click", () => {
      const isOpen = navToggle.getAttribute("aria-expanded") === "true";
      if (!isOpen) closeAccountMenus();
      navToggle.setAttribute("aria-expanded", String(!isOpen));
      primaryNav.dataset.open = String(!isOpen);
    });

    document.addEventListener("click", (event) => {
      if (!primaryNav.contains(event.target) && !navToggle.contains(event.target)) {
        closeNavigation();
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 760) closeNavigation();
    });
  }

  accountMenus.forEach((menu) => {
    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      closeAccountMenus(menu);
      closeNavigation();
      $$("details.action-menu[open], details.row-menu[open]").forEach((details) => {
        details.removeAttribute("open");
      });
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-account-menu]")) {
      closeAccountMenus();
    }
  });

  const closeHelpPopovers = (exceptTrigger = null) => {
    $$("[data-help-trigger]").forEach((trigger) => {
      if (trigger === exceptTrigger) return;
      trigger.setAttribute("aria-expanded", "false");
      const popover = document.getElementById(trigger.getAttribute("aria-controls"));
      if (popover) popover.hidden = true;
    });
  };

  $$("[data-help-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const popover = document.getElementById(trigger.getAttribute("aria-controls"));
      if (!popover) return;
      const willOpen = popover.hidden;
      closeHelpPopovers(trigger);
      popover.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-help-popover]")) closeHelpPopovers();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeNavigation();
    closeHelpPopovers();
    $$("details[open]").forEach((details) => details.removeAttribute("open"));
  });

  $$("[data-dismiss-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const message = button.closest("[data-message]");
      if (message) message.remove();
    });
  });

  const legacyCopyText = (text) => {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.inset = "0 auto auto 0";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  };

  const copyText = async (text) => {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (_error) {
        // Fall back for browsers that expose Clipboard but deny this page access.
      }
    }
    if (!legacyCopyText(text)) throw new Error("Clipboard access is unavailable.");
  };

  $$("[data-copy-prompt]").forEach((button) => {
    const source = document.getElementById(button.dataset.copyPrompt);
    const card = button.closest(".side-card--assistant");
    const status = card ? $("[data-copy-status]", card) : null;
    const label = $("[data-copy-label]", button);
    const originalLabel = label ? label.textContent : button.textContent;
    let resetTimer;

    button.addEventListener("click", async () => {
      const prompt = source ? source.textContent.replace(/\s+/g, " ").trim() : "";
      window.clearTimeout(resetTimer);

      if (!prompt) {
        if (status) status.textContent = "The batch prompt is unavailable.";
        return;
      }

      button.disabled = true;
      try {
        await copyText(prompt);
        if (label) label.textContent = "Copied";
        else button.textContent = "Copied";
        if (status) status.textContent = "Batch prompt copied.";
      } catch (_error) {
        if (status) {
          status.textContent =
            "Copy failed. In ChatGPT, ask Mead Tracker to list your batches and choose this one.";
        }
      } finally {
        resetTimer = window.setTimeout(() => {
          if (label) label.textContent = originalLabel;
          else button.textContent = originalLabel;
          button.disabled = false;
          if (status) status.textContent = "";
        }, 3000);
      }
    });
  });

  $$("[data-password-toggle]").forEach((button) => {
    const field = button.closest(".password-field");
    const input = field ? $("input", field) : null;
    const label = $("[data-password-label]", button);
    if (!input) return;

    button.addEventListener("click", () => {
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.setAttribute("aria-pressed", String(!showing));
      button.setAttribute("aria-label", showing ? "Show password" : "Hide password");
      if (label) label.textContent = showing ? "Show" : "Hide";
    });
  });

  const batchSearch = $("[data-batch-search]");
  const batchCards = $$("[data-batch-card]");
  const searchEmpty = $("[data-search-empty]");

  if (batchSearch && batchCards.length) {
    batchSearch.addEventListener("input", () => {
      const query = batchSearch.value.trim().toLocaleLowerCase();
      let visible = 0;

      batchCards.forEach((card) => {
        const text = (card.dataset.searchText || card.textContent).toLocaleLowerCase();
        const matches = !query || text.includes(query);
        card.hidden = !matches;
        if (matches) visible += 1;
      });

      if (searchEmpty) searchEmpty.hidden = visible !== 0;
    });
  }

  const userSearch = $("[data-user-search]");
  const userRows = $$("[data-user-row]");
  const userSearchEmpty = $("[data-user-search-empty]");

  if (userSearch && userRows.length) {
    userSearch.addEventListener("input", () => {
      const query = userSearch.value.trim().toLocaleLowerCase();
      let visible = 0;

      userRows.forEach((row) => {
        const text = (row.dataset.searchText || row.textContent).toLocaleLowerCase();
        const matches = !query || text.includes(query);
        row.hidden = !matches;
        if (matches) visible += 1;
      });

      if (userSearchEmpty) userSearchEmpty.hidden = visible !== 0;
    });
  }

  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.dataset.confirm;
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  const closeOtherMenus = (current) => {
    $$("details.action-menu[open], details.row-menu[open]").forEach((details) => {
      if (details !== current) details.removeAttribute("open");
    });
  };

  $$("details.action-menu, details.row-menu").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (details.open) {
        closeOtherMenus(details);
        closeAccountMenus();
      }
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("details.action-menu, details.row-menu")) {
      closeOtherMenus(null);
    }
  });

  const printButton = $("[data-print-page]");
  if (printButton) {
    printButton.addEventListener("click", () => window.print());
  }

  const photoLightbox = $("[data-photo-lightbox]");
  const photoLightboxImage = photoLightbox
    ? $("[data-photo-lightbox-image]", photoLightbox)
    : null;
  const photoLightboxCaption = photoLightbox
    ? $("[data-photo-lightbox-caption]", photoLightbox)
    : null;
  const photoLightboxClose = photoLightbox
    ? $("[data-photo-lightbox-close]", photoLightbox)
    : null;

  if (
    photoLightbox
    && photoLightboxImage
    && typeof photoLightbox.showModal === "function"
  ) {
    $$('[data-photo-lightbox-trigger]').forEach((trigger) => {
      trigger.addEventListener("click", (event) => {
        const thumbnail = $("img", trigger);
        const description = thumbnail && thumbnail.alt
          ? thumbnail.alt
          : "Observation photo";

        event.preventDefault();
        photoLightboxImage.src = trigger.href;
        photoLightboxImage.alt = description;
        if (photoLightboxCaption) photoLightboxCaption.textContent = description;
        photoLightbox.showModal();
      });
    });

    if (photoLightboxClose) {
      photoLightboxClose.addEventListener("click", () => photoLightbox.close());
    }

    photoLightbox.addEventListener("click", (event) => {
      if (event.target === photoLightbox) photoLightbox.close();
    });

    photoLightbox.addEventListener("close", () => {
      photoLightboxImage.removeAttribute("src");
      photoLightboxImage.alt = "";
    });
  }

  const labelForm = $("[data-label-options]");
  if (labelForm) {
    const preset = $('[name="preset"]', labelForm);
    const customFields = [$(".field--width", labelForm), $(".field--height", labelForm)].filter(Boolean);

    const syncCustomFields = () => {
      const custom = preset && preset.value === "custom";
      customFields.forEach((field) => {
        field.hidden = !custom;
        $$("input, select", field).forEach((input) => {
          input.disabled = !custom;
        });
      });
    };

    if (preset) {
      preset.addEventListener("change", syncCustomFields);
      syncCustomFields();
    }
  }

  const chartCanvas = $("[data-gravity-chart]");
  const chartDataNode = $("#gravity-chart-data");
  let chartData = null;

  if (chartCanvas && chartDataNode) {
    try {
      chartData = JSON.parse(chartDataNode.textContent);
    } catch (_error) {
      chartData = null;
    }
  }

  const normalizedChartPoints = (data) => {
    if (!data) return [];
    if (Array.isArray(data)) {
      return data
        .map((item, index) => ({
          label: item.label || item.date || item.measured_at || String(index + 1),
          value: Number(item.value ?? item.sg ?? item.specific_gravity),
        }))
        .filter((item) => Number.isFinite(item.value));
    }

    const labels = Array.isArray(data.labels) ? data.labels : [];
    const values = Array.isArray(data.values) ? data.values : [];
    return values
      .map((value, index) => ({
        label: labels[index] || String(index + 1),
        value: Number(value),
      }))
      .filter((item) => Number.isFinite(item.value));
  };

  const drawGravityChart = () => {
    if (!chartCanvas || !chartData) return;
    const points = normalizedChartPoints(chartData);
    const rect = chartCanvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    chartCanvas.width = Math.round(rect.width * ratio);
    chartCanvas.height = Math.round(rect.height * ratio);

    const context = chartCanvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, rect.width, rect.height);

    const rootStyles = getComputedStyle(document.documentElement);
    const chartColor = (name, fallback) => (
      rootStyles.getPropertyValue(name).trim() || fallback
    );
    const textColor = chartColor("--chart-text", "#77655a");
    const gridColor = chartColor("--chart-grid", "rgba(95, 77, 65, 0.13)");
    const lineColor = chartColor("--chart-line", "#aa6819");
    const fillStart = chartColor("--chart-fill-start", "rgba(201, 131, 37, 0.22)");
    const fillEnd = chartColor("--chart-fill-end", "rgba(201, 131, 37, 0.015)");
    const pointFill = chartColor("--chart-point-fill", "#fffdf8");

    const width = rect.width;
    const height = rect.height;
    const padding = {
      top: 28,
      right: Math.max(25, Math.min(46, width * 0.05)),
      bottom: 42,
      left: width < 500 ? 48 : 58,
    };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const font = getComputedStyle(document.body).fontFamily;

    if (!points.length) {
      context.fillStyle = textColor;
      context.font = `600 13px ${font}`;
      context.textAlign = "center";
      context.fillText("Add a gravity reading to start the chart.", width / 2, height / 2);
      return;
    }

    const values = points.map((point) => point.value);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const spread = Math.max(rawMax - rawMin, 0.01);
    const min = Math.max(0.95, rawMin - spread * 0.16);
    const max = rawMax + spread * 0.16;
    const gridLines = 4;

    const xAt = (index) => (
      points.length === 1
        ? padding.left + plotWidth / 2
        : padding.left + (index / (points.length - 1)) * plotWidth
    );
    const yAt = (value) => padding.top + ((max - value) / (max - min)) * plotHeight;

    context.lineWidth = 1;
    context.textBaseline = "middle";
    context.textAlign = "right";
    context.font = `600 11px ${font}`;

    for (let index = 0; index <= gridLines; index += 1) {
      const fraction = index / gridLines;
      const y = padding.top + fraction * plotHeight;
      const value = max - fraction * (max - min);

      context.strokeStyle = gridColor;
      context.beginPath();
      context.moveTo(padding.left, y);
      context.lineTo(width - padding.right, y);
      context.stroke();

      context.fillStyle = textColor;
      context.fillText(value.toFixed(3), padding.left - 9, y);
    }

    const gradient = context.createLinearGradient(0, padding.top, 0, height - padding.bottom);
    gradient.addColorStop(0, fillStart);
    gradient.addColorStop(1, fillEnd);

    context.beginPath();
    points.forEach((point, index) => {
      const x = xAt(index);
      const y = yAt(point.value);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.lineTo(xAt(points.length - 1), height - padding.bottom);
    context.lineTo(xAt(0), height - padding.bottom);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();

    context.beginPath();
    points.forEach((point, index) => {
      const x = xAt(index);
      const y = yAt(point.value);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.strokeStyle = lineColor;
    context.lineWidth = 2.5;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.stroke();

    points.forEach((point, index) => {
      const x = xAt(index);
      const y = yAt(point.value);
      context.beginPath();
      context.arc(x, y, 4.2, 0, Math.PI * 2);
      context.fillStyle = pointFill;
      context.fill();
      context.strokeStyle = lineColor;
      context.lineWidth = 2.4;
      context.stroke();
    });

    const labelIndexes = points.length <= 4
      ? points.map((_point, index) => index)
      : [0, Math.floor((points.length - 1) / 2), points.length - 1];

    context.fillStyle = textColor;
    context.font = `600 10px ${font}`;
    context.textBaseline = "top";
    labelIndexes.forEach((index, labelIndex) => {
      const label = String(points[index].label);
      const x = xAt(index);
      context.textAlign = labelIndex === 0 ? "left" : (labelIndex === labelIndexes.length - 1 ? "right" : "center");
      context.fillText(label.length > 18 ? `${label.slice(0, 17)}…` : label, x, height - padding.bottom + 12);
    });
  };

  if (chartCanvas && chartData) {
    drawGravityChart();
    let redrawTimer;
    window.addEventListener("resize", () => {
      window.clearTimeout(redrawTimer);
      redrawTimer = window.setTimeout(drawGravityChart, 120);
    });
    window.addEventListener("meadtracker:themechange", drawGravityChart);
  }

  $$("textarea").forEach((textarea) => {
    const resize = () => {
      if (textarea.scrollHeight > textarea.clientHeight) {
        textarea.style.height = "auto";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 420)}px`;
      }
    };
    textarea.addEventListener("input", resize);
  });

  $$("[data-observation-photo]").forEach((input) => {
    const selectionStatus = document.createElement("span");
    selectionStatus.className = "photo-selection-status";
    selectionStatus.setAttribute("aria-live", "polite");
    selectionStatus.textContent = "No photo selected.";
    input.insertAdjacentElement("afterend", selectionStatus);

    input.addEventListener("change", () => {
      const photo = input.files && input.files[0];
      selectionStatus.textContent = photo
        ? `Selected: ${photo.name}`
        : "No photo selected.";
      selectionStatus.dataset.selected = String(Boolean(photo));
    });
  });
})();
