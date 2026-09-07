(function () {
  "use strict";

  /* ── Data ────────────────────────────────────────────── */
  var reports = JSON.parse(
    document.getElementById("report-data").textContent || "[]",
  );
  var appData = JSON.parse(
    (document.getElementById("app-data") || { textContent: "{}" })
      .textContent || "{}",
  );
  var networkData = JSON.parse(
    (document.getElementById("network-data") || { textContent: "{}" })
      .textContent || "{}",
  );
  var thresholdData = JSON.parse(
    (document.getElementById("threshold-data") || { textContent: "{}" })
      .textContent || "{}",
  );
  var selectedIndices = [];
  var configData = null;
  var editingPathIdx = -1;

  /* ── Element cache ───────────────────────────────────── */
  function q(id) {
    return document.getElementById(id);
  }
  var els = {
    subtitle: q("subtitle"),
    metaServerId: q("metaServerId"),
    metaHostname: q("metaHostname"),
    metaGenerated: q("metaGenerated"),
    metaPrev: q("metaPrev"),
    metaCurr: q("metaCurr"),
    countAdded: q("countAdded"),
    countDeleted: q("countDeleted"),
    countModified: q("countModified"),
    countUnchanged: q("countUnchanged"),
    segAdded: document.querySelector(".seg-added"),
    segDeleted: document.querySelector(".seg-deleted"),
    segModified: document.querySelector(".seg-modified"),
    segUnchanged: document.querySelector(".seg-unchanged"),
    driftTopContent: q("driftTopContent"),
    driftAuditContent: q("driftAuditContent"),
    emptyState: q("emptyState"),
    addedSection: q("addedSection"),
    deletedSection: q("deletedSection"),
    modifiedSection: q("modifiedSection"),
    addedList: q("addedList"),
    deletedList: q("deletedList"),
    modifiedList: q("modifiedList"),
    addedTitleCount: q("addedTitleCount"),
    deletedTitleCount: q("deletedTitleCount"),
    modifiedTitleCount: q("modifiedTitleCount"),
    searchBox: q("searchBox"),
    themeToggle: q("themeToggle"),
    reportTrigger: q("reportTrigger"),
    reportDropdown: q("reportDropdown"),
    reportSelectedText: q("reportSelectedText"),
    reportCheckboxes: q("reportCheckboxes"),
    compareReportsToggle: q("compareReportsToggle"),
    searchFieldWrap: q("searchFieldWrap"),
    badgeReports: q("badge-reports"),
    badgeApp: q("badge-app"),
    badgeNetwork: q("badge-network"),
    appDriftReportSection: q("appDriftReportSection"),
    appDriftReportCount: q("appDriftReportCount"),
    appDriftReportContent: q("appDriftReportContent"),
    networkDriftReportSection: q("networkDriftReportSection"),
    networkDriftReportCount: q("networkDriftReportCount"),
    networkDriftReportContent: q("networkDriftReportContent"),
    appAuditContent: q("appAuditContent"),
    netAuditContent: q("netAuditContent"),
  };

  /* ── Utils ───────────────────────────────────────────── */
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function animateCount(el, target) {
    var start = 0;
    var duration = 500;
    var startTime = null;
    function step(ts) {
      if (!startTime) startTime = ts;
      var progress = Math.min((ts - startTime) / duration, 1);
      var ease = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(ease * target);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function showToast(msg, type) {
    var c = q("toastContainer");
    var t = document.createElement("div");
    t.className = "toast toast-" + (type || "info");
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(function () {
      t.style.opacity = "0";
      t.style.transform = "translateX(30px) scale(0.9)";
      t.style.transition = "all .25s ease";
      setTimeout(function () {
        if (t.parentNode) t.parentNode.removeChild(t);
      }, 280);
    }, 3200);
  }

  function formatBytes(b) {
    var u = ["B", "KB", "MB", "GB"];
    var s = b;
    var i = 0;
    while (s >= 1024 && i < u.length - 1) {
      s /= 1024;
      i++;
    }
    return s.toFixed(1) + " " + u[i];
  }

  function formatDate(iso) {
    if (!iso) return "—";
    try {
      var s = String(iso).trim();
      if (/^\d{4}_\d{2}_\d{2}/.test(s)) {
        s = s
          .replace(/^(\d{4})_(\d{2})_(\d{2})/, "$1-$2-$3")
          .replace(/T(\d{2})_(\d{2})_(\d{2})/, "T$1:$2:$3")
          .replace(/([+-]\d{2})_(\d{2})$/, "$1:$2");
      }
      var d = new Date(s.replace(" ", "T"));
      if (isNaN(d.getTime())) return iso;
      return (
        d.toLocaleString("en-IN", {
          timeZone: "Asia/Kolkata",
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }) + " IST"
      );
    } catch (e) {
      return iso || "—";
    }
  }

  function formatEntityName(name) {
    if (!name) return "";
    var filename = name.split("/").pop().split("\\").pop();
    var ext = "";
    var dotIdx = filename.lastIndexOf(".");
    var stem = filename;
    if (dotIdx !== -1) {
      stem = filename.slice(0, dotIdx);
      ext = filename.slice(dotIdx);
    }
    var preMatch = stem.match(
      /^(report|snapshot|latest_report|latest_snapshot)_(.+)$/i,
    );
    if (!preMatch) return filename;
    var prefix = preMatch[1];
    var remainder = preMatch[2];

    // 1. Check for ISO-like timestamp: e.g. web01_2026_09_05T18_27_35.165669+00_00
    var isoMatch = remainder.match(
      /^(.*?)_?(\d{4}[-_]\d{2}[-_]\d{2}T\d{2}[_:]\d{2}[_:]\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}[_:]?\d{2})?)$/i,
    );
    if (isoMatch) {
      var sid = isoMatch[1] || "";
      var rawIso = isoMatch[2];
      var normIso = rawIso
        .replace(/^(\d{4})_(\d{2})_(\d{2})/, "$1-$2-$3")
        .replace(/T(\d{2})_(\d{2})_(\d{2})/, "T$1:$2:$3")
        .replace(/([+-]\d{2})_(\d{2})$/, "$1:$2");
      var d = new Date(normIso);
      if (!isNaN(d.getTime())) {
        var parts = new Intl.DateTimeFormat("en-GB", {
          timeZone: "Asia/Kolkata",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).formatToParts(d);
        var p = {};
        parts.forEach(function (x) {
          p[x.type] = x.value;
        });
        var tsStr =
          p.year + "_" + p.month + "_" + p.day + "_" + p.hour + "_" + p.minute;
        return (sid ? prefix + "_" + sid : prefix) + "_" + tsStr + ext;
      }
    }

    // 2. Check for underscore-separated format: web01_2026_09_05_18_27_35 or web01_2026_09_05_23_57
    var stdMatch = remainder.match(
      /^(.*?)_?(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})(?:_(\d{2}))?(?:_(\d+))?$/,
    );
    if (stdMatch) {
      var sid2 = stdMatch[1] || "";
      var y = parseInt(stdMatch[2], 10);
      var mo = parseInt(stdMatch[3], 10) - 1;
      var day = parseInt(stdMatch[4], 10);
      var hr = parseInt(stdMatch[5], 10);
      var min = parseInt(stdMatch[6], 10);
      var sec =
        stdMatch[7] !== undefined ? parseInt(stdMatch[7], 10) : undefined;
      var counter = stdMatch[8] ? "_" + stdMatch[8] : "";

      if (sec !== undefined) {
        var utcDate = new Date(Date.UTC(y, mo, day, hr, min, sec));
        var p2 = {};
        new Intl.DateTimeFormat("en-GB", {
          timeZone: "Asia/Kolkata",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })
          .formatToParts(utcDate)
          .forEach(function (x) {
            p2[x.type] = x.value;
          });
        var tsStr2 =
          p2.year +
          "_" +
          p2.month +
          "_" +
          p2.day +
          "_" +
          p2.hour +
          "_" +
          p2.minute;
        return (
          (sid2 ? prefix + "_" + sid2 : prefix) +
          "_" +
          tsStr2 +
          counter +
          ext
        );
      } else {
        var tsStr3 =
          stdMatch[2] +
          "_" +
          stdMatch[3] +
          "_" +
          stdMatch[4] +
          "_" +
          stdMatch[5] +
          "_" +
          stdMatch[6];
        return (
          (sid2 ? prefix + "_" + sid2 : prefix) +
          "_" +
          tsStr3 +
          counter +
          ext
        );
      }
    }

    return filename;
  }

  /* ── Theme ───────────────────────────────────────────── */
  var THEME_KEY = "snp_theme";
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    q("iconDark").style.display = t === "dark" ? "" : "none";
    q("iconLight").style.display = t === "light" ? "" : "none";
  }
  els.themeToggle.addEventListener("click", function () {
    var next =
      document.documentElement.getAttribute("data-theme") === "dark"
        ? "light"
        : "dark";
    applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (e) {}
  });
  var saved = null;
  try {
    saved = localStorage.getItem(THEME_KEY);
  } catch (e) {}
  applyTheme(saved || "dark");

  /* ── Tab switching ───────────────────────────────────── */
  var TAB_IDS = ["reports", "app", "network", "config"];
  function switchTab(name) {
    TAB_IDS.forEach(function (id) {
      var view = q(id + "View");
      var btn = q("tab-" + id);
      if (!view || !btn) return;
      var active = id === name;
      view.style.display = active ? "" : "none";
      view.classList.toggle("active-view", active);
      btn.classList.toggle("active", active);
    });
    /* Show/hide search only for reports tab */
    if (els.searchFieldWrap)
      els.searchFieldWrap.style.display = name === "reports" ? "" : "none";

    if (name === "config") loadConfig();
    if (name === "app") {
      renderAppData();
      renderAppAudit();
    }
    if (name === "network") {
      renderNetworkData();
      renderNetworkAudit();
    }
  }

  document.getElementById("tabNav").addEventListener("click", function (e) {
    var btn = e.target.closest(".tab-btn");
    if (btn) switchTab(btn.dataset.tab);
  });

  /* ── Multi-select dropdown ───────────────────────────── */
  function populateMultiSelect() {
    els.reportCheckboxes.innerHTML = reports
      .map(function (r, i) {
        var basename = r.file ? r.file.split("/").pop().split("\\").pop() : "";
        var rMeta = (thresholdData.reports || {})[basename];
        var badgeHtml = "";
        if (rMeta && rMeta.threshold_exceeded && rMeta.status === "pending") {
          badgeHtml =
            ' <span class="warning-badge" title="' +
            esc(rMeta.report_label) +
            '">⚠</span>';
        }
        return (
          '<label class="ms-option">' +
          '<input type="checkbox" value="' +
          i +
          '">' +
          '<span class="ms-option-label" title="' +
          esc(r.label) +
          '">' +
          esc(r.label) +
          badgeHtml +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function getSelectedIndices() {
    var out = [];
    els.reportCheckboxes
      .querySelectorAll('input[type="checkbox"]')
      .forEach(function (cb) {
        if (cb.checked) out.push(parseInt(cb.value, 10));
      });
    return out;
  }

  function updateTriggerText() {
    var n = selectedIndices.length;
    if (n === 0) els.reportSelectedText.textContent = "Select reports\u2026";
    else if (n === 1)
      els.reportSelectedText.textContent = reports[selectedIndices[0]].label;
    else if (n === reports.length)
      els.reportSelectedText.textContent = "All reports (" + n + ")";
    else els.reportSelectedText.textContent = n + " reports selected";
  }

  function comparisonMode() {
    return els.compareReportsToggle && els.compareReportsToggle.checked;
  }

  function selectOnly(index) {
    els.reportCheckboxes
      .querySelectorAll('input[type="checkbox"]')
      .forEach(function (cb) {
        cb.checked = parseInt(cb.value, 10) === index;
      });
    selectedIndices = getSelectedIndices();
  }

  els.reportTrigger.addEventListener("click", function (e) {
    e.stopPropagation();
    document.getElementById("reportMultiSelect").classList.toggle("open");
    els.reportDropdown.classList.toggle("open");
  });
  document.addEventListener("click", function (e) {
    var ms = q("reportMultiSelect");
    if (!ms.contains(e.target)) {
      ms.classList.remove("open");
      els.reportDropdown.classList.remove("open");
    }
  });
  els.reportCheckboxes.addEventListener("change", function (event) {
    if (!comparisonMode()) selectOnly(parseInt(event.target.value, 10));
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    if (selectedIndices.length) renderMultiple(selectedIndices);
  });
  q("selectAll").addEventListener("click", function (e) {
    e.stopPropagation();
    if (!comparisonMode()) {
      showToast(
        "Enable Compare reports to select more than one report",
        "info",
      );
      return;
    }
    els.reportCheckboxes
      .querySelectorAll('input[type="checkbox"]')
      .forEach(function (cb) {
        cb.checked = true;
      });
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    if (selectedIndices.length) renderMultiple(selectedIndices);
  });
  q("deselectAll").addEventListener("click", function (e) {
    e.stopPropagation();
    els.reportCheckboxes
      .querySelectorAll('input[type="checkbox"]')
      .forEach(function (cb) {
        cb.checked = false;
      });
    selectedIndices = [];
    updateTriggerText();
  });
  els.compareReportsToggle.addEventListener("change", function () {
    if (!comparisonMode() && selectedIndices.length > 1)
      selectOnly(selectedIndices[selectedIndices.length - 1]);
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    if (selectedIndices.length) renderMultiple(selectedIndices);
  });

  /* ── Diff rendering ──────────────────────────────────── */
  function renderDiffLines(lines) {
    return (lines || [])
      .map(function (line) {
        var cls = "diff-line";
        if (line.startsWith("+++") || line.startsWith("---"))
          cls += " diff-file";
        else if (line.startsWith("@@")) cls += " diff-hunk";
        else if (line.startsWith("+")) cls += " diff-add";
        else if (line.startsWith("-")) cls += " diff-del";
        var cleaned = line.replace(/\\n$/, "");
        cleaned = cleaned.replace(
          /(\d{4}[-_]\d{2}[-_]\d{2}[T ]\d{2}[:_]\d{2}[:_]\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}[:_]?\d{2})?)/g,
          function (m) {
            return formatDate(m);
          },
        );
        return '<div class="' + cls + '">' + esc(cleaned) + "</div>";
      })
      .join("");
  }

  function formatFieldValue(key, val) {
    if (val === null || val === undefined) return "—";
    if (
      key === "mtime" ||
      key === "ctime" ||
      (typeof val === "string" &&
        /^\d{4}[-_]\d{2}[-_]\d{2}[T ]\d{2}[:_]\d{2}/.test(val))
    ) {
      return formatDate(val);
    }
    return String(val);
  }

  function fieldRows(changes) {
    return Object.keys(changes || {})
      .map(function (k) {
        var v = changes[k] || {};
        return (
          '<tr><td class="field-name">' +
          esc(k) +
          "</td>" +
          '<td class="val-old">' +
          esc(formatFieldValue(k, v.old)) +
          "</td>" +
          '<td class="val-new">' +
          esc(formatFieldValue(k, v["new"])) +
          "</td></tr>"
        );
      })
      .join("");
  }

  /* ── Drift reports render ────────────────────────────── */
  function renderMultiple(indices) {
    if (!indices.length) return;
    if (comparisonMode()) {
      renderReportComparison(indices);
      return;
    }
    var allAdded = [],
      allDeleted = [],
      allModified = [];
    var totalUnchanged = 0;
    var serverIds = {},
      hostnames = {},
      genAts = [];
    // var showBadge = comparisonMode() && indices.length > 1;
    var showBadge = indices.length > 1;

    indices.forEach(function (i) {
      var entry = reports[i];
      if (!entry) return;
      var r = entry.data;
      var lbl = entry.label;
      (r.added || []).forEach(function (x) {
        allAdded.push({ path: x.path, type: x.type, _r: lbl });
      });
      (r.deleted || []).forEach(function (x) {
        allDeleted.push({ path: x.path, type: x.type, _r: lbl });
      });
      (r.modified || []).forEach(function (x) {
        allModified.push({
          path: x.path,
          changes: x.changes,
          content_diff: x.content_diff,
          content_note: x.content_note,
          _r: lbl,
        });
      });
      totalUnchanged = (r.summary || {}).unchanged || 0;
      serverIds[r.server_id || ""] = true;
      hostnames[r.hostname || ""] = true;
      if (r.generated_at) genAts.push(r.generated_at);
    });

    var pendingExceeded = [];
    indices.forEach(function (i) {
      var entry = reports[i];
      if (!entry) return;
      var basename = entry.file
        ? entry.file.split("/").pop().split("\\").pop()
        : "";
      var isBase = !(entry.data && entry.data.previous_snapshot);
      var rMeta = (thresholdData.reports || {})[basename];
      if (
        rMeta &&
        !isBase &&
        rMeta.threshold_exceeded &&
        rMeta.status === "pending"
      ) {
        pendingExceeded.push(rMeta.report_label);
      }
    });

    var topHtml = "";
    if (pendingExceeded.length > 0) {
      topHtml +=
        '<div class="warning-banner">' +
        '<div class="warning-banner-icon">⚠</div>' +
        '<div class="warning-banner-content">' +
        '<div class="warning-banner-title">Warning: Change threshold exceeded (' +
        (thresholdData.threshold || 0) +
        " max changes allowed)</div>" +
        '<div style="font-size: 0.82rem; color: var(--text-dim); margin-top: 2px;">The following reports require manual approval:</div>' +
        '<ul class="warning-banner-reports">' +
        pendingExceeded
          .map(function (lbl) {
            return "<li>" + esc(lbl) + "</li>";
          })
          .join("") +
        "</ul>" +
        "</div></div>";
    }
    // if (indices.length === 1 && !comparisonMode()) {
    if (indices.length === 1) {
      var entry = reports[indices[0]];
      var basename = entry.file
        ? entry.file.split("/").pop().split("\\").pop()
        : "";
      var rMeta = (thresholdData.reports || {})[basename];
      if (rMeta) {
        var cls =
          rMeta.status === "approved"
            ? "approved"
            : rMeta.status === "rejected"
              ? "rejected"
              : "";
        var statusHtml = "";
        if (rMeta.status === "pending") {
          statusHtml =
            '<span class="status-pill">Use the baseline approval panel below</span>';
        } else if (rMeta.status === "approved") {
          statusHtml =
            '<span class="status-pill approved">&#10003; Approved</span>';
        } else {
          statusHtml =
            '<span class="status-pill rejected">&#10007; Rejected</span>';
        }

        var excText = rMeta.threshold_exceeded
          ? " (⚠ Threshold exceeded: " +
            rMeta.change_count +
            " > " +
            thresholdData.threshold +
            ")"
          : "";
        var metaHtml = "";
        if (rMeta.status !== "pending" && rMeta.decided_at) {
          metaHtml +=
            '<div class="approval-bar-meta">' +
            esc(formatDate(rMeta.decided_at));
          if (rMeta.description)
            metaHtml += " &mdash; " + esc(rMeta.description);
          metaHtml += "</div>";
        }
        topHtml +=
          '<div class="report-approval-bar ' +
          cls +
          '">' +
          '<div class="approval-bar-label">Status for <strong>' +
          esc(rMeta.report_label) +
          "</strong>" +
          excText +
          metaHtml +
          "</div>" +
          statusHtml +
          "</div>";
      }
    }
    if (els.driftTopContent) els.driftTopContent.innerHTML = topHtml;
    renderDriftAudit(indices);

    els.metaServerId.textContent = Object.keys(serverIds).join(", ") || "—";
    els.metaHostname.textContent = Object.keys(hostnames).join(", ") || "—";
    // if (indices.length === 1 && !comparisonMode()) {
    if (indices.length === 1) {
      var sr = reports[indices[0]].data;
      els.metaGenerated.textContent = formatDate(sr.generated_at);
      els.metaPrev.textContent = sr.previous_snapshot
        ? formatEntityName(sr.previous_snapshot)
        : "(none — baseline run)";
      els.metaCurr.textContent = sr.current_snapshot
        ? formatEntityName(sr.current_snapshot)
        : "—";
      els.subtitle.textContent = reports[indices[0]].label;
    } else {
      genAts.sort();
      els.metaGenerated.textContent =
        formatDate(genAts[0]) + " → " + formatDate(genAts[genAts.length - 1]);
      els.metaPrev.textContent = "(" + indices.length + " reports selected)";
      els.metaCurr.textContent = "(" + indices.length + " reports selected)";
      els.subtitle.textContent = comparisonMode()
        ? "Comparison view: " + indices.length + " reports"
        : indices.length + " reports selected";
    }

    animateCount(els.countAdded, allAdded.length);
    animateCount(els.countDeleted, allDeleted.length);
    animateCount(els.countModified, allModified.length);
    animateCount(els.countUnchanged, totalUnchanged);

    var total =
      allAdded.length + allDeleted.length + allModified.length + totalUnchanged;
    function pct(n) {
      return total > 0 ? ((100 * n) / total).toFixed(2) + "%" : "0%";
    }
    els.segAdded.style.width = pct(allAdded.length);
    els.segDeleted.style.width = pct(allDeleted.length);
    els.segModified.style.width = pct(allModified.length);
    els.segUnchanged.style.width = pct(totalUnchanged);

    var hasChanges =
      allAdded.length + allDeleted.length + allModified.length > 0;
    els.emptyState.style.display = hasChanges ? "none" : "";
    els.addedSection.style.display = allAdded.length ? "" : "none";
    els.deletedSection.style.display = allDeleted.length ? "" : "none";
    els.modifiedSection.style.display = allModified.length ? "" : "none";

    els.addedTitleCount.textContent = "(" + allAdded.length + ")";
    els.deletedTitleCount.textContent = "(" + allDeleted.length + ")";
    els.modifiedTitleCount.textContent = "(" + allModified.length + ")";

    function listItem(item) {
      var badge = showBadge
        ? '<span class="report-badge" title="' +
          esc(item._r) +
          '">' +
          esc(item._r) +
          "</span>"
        : "";
      return (
        '<li data-path="' +
        esc(item.path.toLowerCase()) +
        '">' +
        '<span class="type-badge">' +
        esc(item.type || "?") +
        "</span>" +
        "<span>" +
        esc(item.path) +
        "</span>" +
        badge +
        "</li>"
      );
    }
    els.addedList.innerHTML = allAdded.map(listItem).join("");
    els.deletedList.innerHTML = allDeleted.map(listItem).join("");

    els.modifiedList.innerHTML = allModified
      .map(function (item, mi) {
        var fn = Object.keys(item.changes || {}).join(", ");
        var badge = showBadge
          ? '<span class="report-badge" title="' +
            esc(item._r) +
            '">' +
            esc(item._r) +
            "</span>"
          : "";
        var body = "";
        if (item.changes && Object.keys(item.changes).length)
          body +=
            '<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th></tr></thead><tbody>' +
            fieldRows(item.changes) +
            "</tbody></table>";
        if (item.content_note)
          body += '<div class="note-box">' + esc(item.content_note) + "</div>";
        if (item.content_diff && item.content_diff.length)
          body +=
            '<div class="diff-box">' +
            renderDiffLines(item.content_diff) +
            "</div>";
        return (
          '<div class="mod-item" data-path="' +
          esc(item.path.toLowerCase()) +
          '" data-idx="' +
          mi +
          '">' +
          '<div class="mod-header">' +
          '<div><div class="mod-path">' +
          esc(item.path) +
          "</div>" +
          '<div class="mod-fields">changed: ' +
          esc(fn || "(content only)") +
          "</div></div>" +
          badge +
          '<div class="mod-chevron">&#9656;</div></div>' +
          '<div class="mod-body">' +
          body +
          "</div></div>"
        );
      })
      .join("");

    // App Drift section in Reports tab
    var curAppDiff = {};
    var curNetDiff = {};
    if (indices.length === 1) {
      var cr = reports[indices[0]].data || {};
      curAppDiff = cr.app_diff || thresholdData.app_diff || {};
      curNetDiff = cr.network_diff || thresholdData.network_diff || {};
    } else {
      curAppDiff = thresholdData.app_diff || {};
      curNetDiff = thresholdData.network_diff || {};
    }

    var appAddedList = curAppDiff.added_apps || [];
    var appRemovedList = curAppDiff.removed_apps || [];
    var appUpdatedList = curAppDiff.updated_apps || [];
    var appDriftCount = appAddedList.length + appRemovedList.length + appUpdatedList.length;

    if (els.appDriftReportSection && els.appDriftReportContent) {
      if (appDriftCount > 0) {
        els.appDriftReportSection.style.display = "";
        if (els.appDriftReportCount)
          els.appDriftReportCount.textContent = "(" + appDriftCount + ")";
        var appHtml = "";
        if (appAddedList.length) {
          appHtml +=
            '<div class="drift-card-group"><div class="drift-card-header"><span class="status-pill approved">+ ' +
            appAddedList.length +
            " Added Binaries / Scripts</span></div>" +
            '<ul class="path-list">' +
            appAddedList
              .map(function (item) {
                var p =
                  typeof item === "string"
                    ? item
                    : item.path || item.name || "";
                var t =
                  typeof item === "object"
                    ? item.subtype || item.type || "file"
                    : "file";
                return (
                  '<li><span class="type-badge">' +
                  esc(t) +
                  "</span><span>" +
                  esc(p) +
                  "</span></li>"
                );
              })
              .join("") +
            "</ul></div>";
        }
        if (appRemovedList.length) {
          appHtml +=
            '<div class="drift-card-group"><div class="drift-card-header"><span class="status-pill rejected">- ' +
            appRemovedList.length +
            " Removed Binaries / Scripts</span></div>" +
            '<ul class="path-list">' +
            appRemovedList
              .map(function (item) {
                var p =
                  typeof item === "string"
                    ? item
                    : item.path || item.name || "";
                var t =
                  typeof item === "object"
                    ? item.subtype || item.type || "file"
                    : "file";
                return (
                  '<li><span class="type-badge">' +
                  esc(t) +
                  "</span><span>" +
                  esc(p) +
                  "</span></li>"
                );
              })
              .join("") +
            "</ul></div>";
        }
        if (appUpdatedList.length) {
          appHtml +=
            '<div class="drift-card-group"><div class="drift-card-header"><span class="status-pill" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b;">~ ' +
            appUpdatedList.length +
            " Modified Binaries / Scripts</span></div>" +
            '<ul class="path-list">' +
            appUpdatedList
              .map(function (item) {
                var p = item.path || item.name || "";
                var chg = (item.changes || []).join(", ");
                return (
                  '<li><span class="type-badge">modified</span><span>' +
                  esc(p) +
                  ' <small style="color:var(--text-dim);">(' +
                  esc(chg) +
                  ")</small></span></li>"
                );
              })
              .join("") +
            "</ul></div>";
        }
        els.appDriftReportContent.innerHTML = appHtml;
      } else {
        els.appDriftReportSection.style.display = "none";
        els.appDriftReportContent.innerHTML = "";
      }
    }

    // Network Drift section in Reports tab
    var netModifiedMap = curNetDiff.modified_settings || {};
    var netKeys = Object.keys(netModifiedMap);
    var netDriftCount = netKeys.length;

    if (els.networkDriftReportSection && els.networkDriftReportContent) {
      if (netDriftCount > 0) {
        els.networkDriftReportSection.style.display = "";
        if (els.networkDriftReportCount)
          els.networkDriftReportCount.textContent = "(" + netDriftCount + ")";
        var netHtml =
          '<div class="drift-card-group"><div class="drift-card-header"><span class="status-pill" style="background: rgba(239, 68, 68, 0.2); color: #ef4444;">' +
          netDriftCount +
          " Changed Network Properties</span></div>" +
          '<div class="table-wrap"><table class="network-table"><thead><tr><th>Property</th><th>Category</th><th>Baseline Value</th><th>Current Value</th></tr></thead><tbody>';
        netKeys.forEach(function (k) {
          var item = netModifiedMap[k] || {};
          var secName = item.section || "General";
          var oldV =
            item.old !== null && item.old !== undefined
              ? String(item.old)
              : "— (none)";
          var newV =
            item.new !== null && item.new !== undefined
              ? String(item.new)
              : "— (deleted)";
          netHtml +=
            '<tr><td class="mono font-semibold">' +
            esc(k) +
            '</td><td><span class="net-pill-type">' +
            esc(secName) +
            '</span></td><td class="mono text-muted">' +
            esc(oldV) +
            '</td><td class="mono" style="color:var(--red); font-weight:600;">' +
            esc(newV) +
            "</td></tr>";
        });
        netHtml += "</tbody></table></div></div>";
        els.networkDriftReportContent.innerHTML = netHtml;
      } else {
        els.networkDriftReportSection.style.display = "none";
        els.networkDriftReportContent.innerHTML = "";
      }
    }

    var hasChanges =
      allAdded.length +
        allDeleted.length +
        allModified.length +
        appDriftCount +
        netDriftCount >
      0;
    els.emptyState.style.display = hasChanges ? "none" : "";

    applySearchFilter();
    updateTabBadges();
  }

  function renderReportComparison(indices) {
    els.driftAuditContent.innerHTML = "";
    if (indices.length !== 2) {
      els.driftTopContent.innerHTML =
        '<div class="warning-banner"><div class="warning-banner-content"><div class="warning-banner-title">Select exactly two reports to compare</div></div></div>';
      return;
    }
    var baseEntry = reports[indices[0]];
    var targetEntry = reports[indices[1]];
    var baseId = snapshotIdForReport(baseEntry);
    var targetId = snapshotIdForReport(targetEntry);
    var sid = _serverIdFromCentralPath();
    if (!sid || !baseId || !targetId) {
      showToast(
        "Report comparison is available from the Central dashboard",
        "error",
      );
      return;
    }
    fetch("/api/server/" + sid + "/snapshot-compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base: baseId, target: targetId }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || "Report comparison failed");
          return data.report;
        });
      })
      .then(function (report) {
        var summary = report.summary || {};
        var added = report.added || [];
        var deleted = report.deleted || [];
        var modified = report.modified || [];
        els.driftTopContent.innerHTML =
          '<div class="report-approval-bar"><div class="approval-bar-label">Comparison only: <strong>' +
          esc(baseEntry.label) +
          "</strong> to <strong>" +
          esc(targetEntry.label) +
          "</strong></div></div>";
        els.metaServerId.textContent = report.server_id || "-";
        els.metaHostname.textContent = report.hostname || "-";
        els.metaGenerated.textContent = targetEntry.data.generated_at
          ? formatDate(targetEntry.data.generated_at)
          : "-";
        els.metaPrev.textContent = formatEntityName(baseId);
        els.metaCurr.textContent = formatEntityName(targetId);
        els.subtitle.textContent = "Comparison view";
        animateCount(els.countAdded, added.length);
        animateCount(els.countDeleted, deleted.length);
        animateCount(els.countModified, modified.length);
        animateCount(els.countUnchanged, summary.unchanged || 0);
        var total =
          added.length +
          deleted.length +
          modified.length +
          (summary.unchanged || 0);
        function pct(n) {
          return total ? ((n * 100) / total).toFixed(2) + "%" : "0%";
        }
        els.segAdded.style.width = pct(added.length);
        els.segDeleted.style.width = pct(deleted.length);
        els.segModified.style.width = pct(modified.length);
        els.segUnchanged.style.width = pct(summary.unchanged || 0);
        els.emptyState.style.display =
          added.length || deleted.length || modified.length ? "none" : "";
        els.addedSection.style.display = added.length ? "" : "none";
        els.deletedSection.style.display = deleted.length ? "" : "none";
        els.modifiedSection.style.display = modified.length ? "" : "none";
        els.addedTitleCount.textContent = "(" + added.length + ")";
        els.deletedTitleCount.textContent = "(" + deleted.length + ")";
        els.modifiedTitleCount.textContent = "(" + modified.length + ")";
        els.addedList.innerHTML = added
          .map(function (item) {
            return (
              '<li><span class="type-badge">' +
              esc(item.type || "?") +
              "</span><span>" +
              esc(item.path) +
              "</span></li>"
            );
          })
          .join("");
        els.deletedList.innerHTML = deleted
          .map(function (item) {
            return (
              '<li><span class="type-badge">' +
              esc(item.type || "?") +
              "</span><span>" +
              esc(item.path) +
              "</span></li>"
            );
          })
          .join("");
        els.modifiedList.innerHTML = modified
          .map(function (item) {
            return (
              '<div class="mod-item"><div class="mod-header"><div><div class="mod-path">' +
              esc(item.path) +
              '</div><div class="mod-fields">changed: ' +
              esc(Object.keys(item.changes || {}).join(", ")) +
              "</div></div></div></div>"
            );
          })
          .join("");
      })
      .catch(function (error) {
        els.driftTopContent.innerHTML = "";
        showToast(error.message, "error");
      });
  }

  /* Modified item expand/collapse */
  document.addEventListener("click", function (e) {
    var hdr = e.target.closest(".mod-header");
    if (hdr) hdr.parentElement.classList.toggle("open");
  });

  /* Search filter */
  function applySearchFilter() {
    var q2 = (els.searchBox.value || "").trim().toLowerCase();
    document.querySelectorAll("[data-path]").forEach(function (n) {
      var match = !q2 || n.getAttribute("data-path").indexOf(q2) !== -1;
      n.classList.toggle("hidden-by-search", !match);
    });
  }
  els.searchBox.addEventListener("input", applySearchFilter);

  /* ── App Snapshots tab ───────────────────────────────── */
  function renderAppData() {
    var execs = appData.executables || [];
    var scripts = appData.scripts || [];
    var links = appData.symlinks || [];
    var total = execs.length + scripts.length + links.length;
    var hasData = total > 0 || appData.timestamp;

    var noDataEl = q("appNoData");
    var contentEl = q("appContent");
    if (!hasData) {
      if (noDataEl) noDataEl.style.display = "";
      if (contentEl) contentEl.style.display = "none";
      return;
    }
    if (noDataEl) noDataEl.style.display = "none";
    if (contentEl) contentEl.style.display = "";

    animateCount(q("appTotalCount"), total);
    animateCount(q("appExecCount"), execs.length);
    animateCount(q("appScriptCount"), scripts.length);
    animateCount(q("appSymlinkCount"), links.length);
    animateCount(q("cardExecCount"), execs.length);
    animateCount(q("cardScriptCount"), scripts.length);
    animateCount(q("cardLinkCount"), links.length);

    function fillTable(tbody, rows) {
      if (!tbody) return;
      tbody.innerHTML = rows;
      if (!rows)
        tbody.innerHTML =
          '<tr><td colspan="99" class="net-empty">No data</td></tr>';
    }

    var execBody = document.querySelector("#execTable tbody");
    fillTable(
      execBody,
      execs
        .map(function (x) {
          return (
            "<tr><td>" +
            esc(x.name) +
            "</td><td>" +
            formatBytes(x.size || 0) +
            "</td><td>" +
            esc(x.permissions || "—") +
            "</td><td>" +
            formatDate(x.mtime || "") +
            "</td></tr>"
          );
        })
        .join(""),
    );
    q("execTitleCount").textContent = "(" + execs.length + ")";

    var scriptBody = document.querySelector("#scriptTable tbody");
    fillTable(
      scriptBody,
      scripts
        .map(function (x) {
          return (
            "<tr><td>" +
            esc(x.name) +
            "</td><td>" +
            esc(x.subtype || "script") +
            "</td><td>" +
            formatBytes(x.size || 0) +
            "</td><td>" +
            esc(x.permissions || "—") +
            "</td><td>" +
            formatDate(x.mtime || "") +
            "</td></tr>"
          );
        })
        .join(""),
    );
    q("scriptTitleCount").textContent = "(" + scripts.length + ")";

    var linkBody = document.querySelector("#linkTable tbody");
    fillTable(
      linkBody,
      links
        .map(function (x) {
          return (
            "<tr><td>" +
            esc(x.name) +
            "</td><td>" +
            esc(x.target || "—") +
            "</td></tr>"
          );
        })
        .join(""),
    );
    q("linkTitleCount").textContent = "(" + links.length + ")";

    /* Hide empty sub-sections */
    if (q("execSection"))
      q("execSection").style.display = execs.length ? "" : "none";
    if (q("scriptSection"))
      q("scriptSection").style.display = scripts.length ? "" : "none";
    if (q("linkSection"))
      q("linkSection").style.display = links.length ? "" : "none";
  }

  /* ── Network Settings tab — Rich Renderer ───────────────── */

  /* Human-readable label + unit + section for every raw YAML key */
  var NETWORK_LABELS = {
    /* metadata */
    os_version:                    { label: "OS Version",                unit: "",      section: "metadata" },
    kernel_release:                { label: "Kernel Release",            unit: "",      section: "metadata" },
    /* sysctl_kernel */
    kernel_sched_migration_cost_ns:{ label: "Sched Migration Cost",      unit: "ns",    section: "sysctl_kernel" },
    kernel_sched_latency_ns:       { label: "Sched Latency",             unit: "ns",    section: "sysctl_kernel" },
    kernel_sched_min_granularity_ns:{ label: "Sched Min Granularity",    unit: "ns",    section: "sysctl_kernel" },
    kernel_sched_autogroup_enabled:{ label: "Autogroup Scheduling",      unit: "",      section: "sysctl_kernel" },
    net_core_rmem_max:             { label: "Socket Recv Buffer Max",     unit: "bytes", section: "sysctl_kernel" },
    net_core_wmem_max:             { label: "Socket Send Buffer Max",     unit: "bytes", section: "sysctl_kernel" },
    net_ipv4_tcp_rmem:             { label: "TCP Recv Buffer",            unit: "",      section: "sysctl_kernel" },
    net_ipv4_tcp_wmem:             { label: "TCP Send Buffer",            unit: "",      section: "sysctl_kernel" },
    net_ipv4_tcp_fin_timeout:      { label: "TCP FIN Timeout",           unit: "sec",   section: "sysctl_kernel" },
    net_ipv4_tcp_tw_reuse:         { label: "TCP TIME_WAIT Reuse",       unit: "",      section: "sysctl_kernel" },
    net_ipv4_ip_forward:           { label: "IP Forwarding",             unit: "",      section: "sysctl_kernel" },
    net_ipv4_tcp_keepalive_time:   { label: "TCP Keepalive Time",        unit: "sec",   section: "sysctl_kernel" },
    net_ipv4_tcp_keepalive_intvl:  { label: "TCP Keepalive Interval",    unit: "sec",   section: "sysctl_kernel" },
    net_ipv4_tcp_keepalive_probes: { label: "TCP Keepalive Probes",      unit: "",      section: "sysctl_kernel" },
    vm_swappiness:                 { label: "VM Swappiness",             unit: "",      section: "sysctl_kernel" },
    vm_overcommit_memory:          { label: "Memory Overcommit",         unit: "",      section: "sysctl_kernel" },
    fs_file_max:                   { label: "Max Open Files (fs)",       unit: "",      section: "sysctl_kernel" },
    /* cpu_isolation_power */
    isolcpus:                      { label: "Isolated CPUs",             unit: "",      section: "cpu_isolation_power" },
    nohz_full:                     { label: "NOHZ Full CPUs",            unit: "",      section: "cpu_isolation_power" },
    cpufreq_governor:              { label: "CPU Frequency Governor",    unit: "",      section: "cpu_isolation_power" },
    disabled_cstates_cpu0:         { label: "Disabled C-States (cpu0)",  unit: "",      section: "cpu_isolation_power" },
    /* irq_affinity */
    irqbalance_status:             { label: "IRQBalance Status",         unit: "",      section: "irq_affinity" },
    default_smp_affinity:          { label: "Default SMP Affinity",      unit: "",      section: "irq_affinity" },
    /* nic_ethtool */
    sample_physical_interface:     { label: "Interface",                 unit: "",      section: "nic_ethtool" },
    driver:                        { label: "Driver",                    unit: "",      section: "nic_ethtool" },
    driver_version:                { label: "Driver Version",            unit: "",      section: "nic_ethtool" },
    firmware_version:              { label: "Firmware Version",          unit: "",      section: "nic_ethtool" },
    ring_rx:                       { label: "RX Ring Buffer Size",       unit: "desc",  section: "nic_ethtool" },
    ring_tx:                       { label: "TX Ring Buffer Size",       unit: "desc",  section: "nic_ethtool" },
    coalesce_rx_usecs:             { label: "RX Coalescing Delay",       unit: "µs",    section: "nic_ethtool" },
    coalesce_tx_usecs:             { label: "TX Coalescing Delay",       unit: "µs",    section: "nic_ethtool" },
    /* onload_solarflare */
    installed:                     { label: "Installed",                 unit: "",      section: "onload_solarflare" },
    version:                       { label: "Version",                   unit: "",      section: "onload_solarflare" },
    config_present:                { label: "Config Present",            unit: "",      section: "onload_solarflare" },
    /* hugepages_tuned */
    hugepages_2M_nr:               { label: "2M Hugepages",              unit: "pages", section: "hugepages_tuned" },
    hugepages_1G_nr:               { label: "1G Hugepages",              unit: "pages", section: "hugepages_tuned" },
    thp_enabled:                   { label: "Transparent HP Mode",       unit: "",      section: "hugepages_tuned" },
    thp_defrag:                    { label: "Transparent HP Defrag",     unit: "",      section: "hugepages_tuned" },
    tuned_active_profile:          { label: "Tuned Active Profile",      unit: "",      section: "hugepages_tuned" },
    /* time_synchronization */
    chrony_sync_status:            { label: "Chrony Sync Status",        unit: "",      section: "time_synchronization" },
    ntp_active_peer:               { label: "NTP Active Peer",           unit: "",      section: "time_synchronization" },
    ptp4l_status:                  { label: "PTP4L Service Status",      unit: "",      section: "time_synchronization" },
    /* core_services */
    irqbalance:                    { label: "IRQ Balance",               unit: "",      section: "core_services" },
    chronyd:                       { label: "Chrony Daemon",             unit: "",      section: "core_services" },
    haproxy:                       { label: "HAProxy",                   unit: "",      section: "core_services" },
    keepalived:                    { label: "Keepalived",                unit: "",      section: "core_services" },
    ptp4l:                         { label: "PTP4L",                     unit: "",      section: "core_services" },
  };

  /* Section definitions: key, title, icon path, accent CSS var */
  var NETWORK_SECTIONS = [
    {
      key: "metadata",
      title: "OS & Kernel",
      accent: "--net-accent-indigo",
      icon: '<path d="M3 3.5A1.5 1.5 0 014.5 2h7A1.5 1.5 0 0113 3.5v9a1.5 1.5 0 01-1.5 1.5h-7A1.5 1.5 0 013 12.5v-9zm1.5-.5a.5.5 0 00-.5.5v9a.5.5 0 00.5.5h7a.5.5 0 00.5-.5v-9a.5.5 0 00-.5-.5h-7z"/><path d="M5 5.5a.5.5 0 01.5-.5h5a.5.5 0 010 1h-5a.5.5 0 01-.5-.5zm0 2a.5.5 0 01.5-.5h5a.5.5 0 010 1h-5a.5.5 0 01-.5-.5zm0 2a.5.5 0 01.5-.5h3a.5.5 0 010 1h-3a.5.5 0 01-.5-.5z"/>',
    },
    {
      key: "sysctl_kernel",
      title: "Kernel / Sysctl",
      accent: "--net-accent-blue",
      icon: '<path d="M8 4.754a3.246 3.246 0 100 6.492 3.246 3.246 0 000-6.492zM5.754 8a2.246 2.246 0 114.492 0 2.246 2.246 0 01-4.492 0z"/><path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 01-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 01-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 01.52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292-.159a.873.873 0 011.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 011.255-.52l.292.16c1.64.893 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 01.52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 01-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a.873.873 0 01-1.255-.52l-.094-.319z"/>',
    },
    {
      key: "cpu_isolation_power",
      title: "CPU & Power",
      accent: "--net-accent-amber",
      icon: '<path d="M5 0a.5.5 0 01.5.5V2h1V.5a.5.5 0 011 0V2h1V.5a.5.5 0 011 0V2h1V.5a.5.5 0 011 0V2A2.5 2.5 0 0114 4.5h1.5a.5.5 0 010 1H14v1h1.5a.5.5 0 010 1H14v1h1.5a.5.5 0 010 1H14v1h1.5a.5.5 0 010 1H14A2.5 2.5 0 0111.5 14v1.5a.5.5 0 01-1 0V14h-1v1.5a.5.5 0 01-1 0V14h-1v1.5a.5.5 0 01-1 0V14A2.5 2.5 0 012 11.5H.5a.5.5 0 010-1H2v-1H.5a.5.5 0 010-1H2v-1H.5a.5.5 0 010-1H2A2.5 2.5 0 014.5 2V.5A.5.5 0 015 0zm-.5 3A1.5 1.5 0 003 4.5v7A1.5 1.5 0 004.5 13h7a1.5 1.5 0 001.5-1.5v-7A1.5 1.5 0 0011.5 3h-7z"/>',
    },
    {
      key: "irq_affinity",
      title: "IRQ Affinity",
      accent: "--net-accent-purple",
      icon: '<path d="M11.5 8a3.5 3.5 0 11-7 0 3.5 3.5 0 017 0zm-3.5 2a2 2 0 100-4 2 2 0 000 4z"/><path d="M3.25 8A4.75 4.75 0 018 3.25v-1.5A6.25 6.25 0 001.75 8h1.5zm4.75 4.75A4.75 4.75 0 013.25 8h-1.5A6.25 6.25 0 008 14.25v-1.5zm4.75-4.75A4.75 4.75 0 018 12.75v1.5A6.25 6.25 0 0014.25 8h-1.5zm-4.75-4.75A4.75 4.75 0 0112.75 8h1.5A6.25 6.25 0 008 1.75v1.5z"/>',
    },
    {
      key: "nic_ethtool",
      title: "NIC & Ethtool",
      accent: "--net-accent-teal",
      icon: '<path d="M0 4a2 2 0 012-2h12a2 2 0 012 2v8a2 2 0 01-2 2H2a2 2 0 01-2-2V4zm2.5 1a.5.5 0 000 1h11a.5.5 0 000-1h-11zM2 8.5a.5.5 0 01.5-.5h3a.5.5 0 010 1h-3a.5.5 0 01-.5-.5zm0 2a.5.5 0 01.5-.5h7a.5.5 0 010 1h-7a.5.5 0 01-.5-.5z"/>',
    },
    {
      key: "onload_solarflare",
      title: "Onload / Solarflare",
      accent: "--net-accent-sky",
      icon: '<path d="M9.293 0H4a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V4.707A1 1 0 0013.707 4L10 .293A1 1 0 009.293 0zM9.5 3.5v-2l3 3h-2a1 1 0 01-1-1z"/>',
    },
    {
      key: "hugepages_tuned",
      title: "Hugepages & Tuned",
      accent: "--net-accent-orange",
      icon: '<path d="M0 2a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1v10.5a.5.5 0 01-.5.5h-13a.5.5 0 01-.5-.5V5a1 1 0 01-1-1V2zm2 3v10h12V5H2zm13-2H1v1h14V3z"/>',
    },
    {
      key: "time_synchronization",
      title: "Time Synchronization",
      accent: "--net-accent-green",
      icon: '<path d="M8 3.5a.5.5 0 00-1 0V9a.5.5 0 00.252.434l3.5 2a.5.5 0 00.496-.868L8 8.71V3.5z"/><path d="M8 16A8 8 0 108 0a8 8 0 000 16zm7-8A7 7 0 111 8a7 7 0 0114 0z"/>',
    },
    {
      key: "core_services",
      title: "Core Services",
      accent: "--net-accent-red",
      icon: '<path d="M8 1a7 7 0 100 14A7 7 0 008 1zM0 8a8 8 0 1116 0A8 8 0 010 8z"/><path d="M6.5 5.5v5a.5.5 0 001 0v-5a.5.5 0 00-1 0zm3 0v5a.5.5 0 001 0v-5a.5.5 0 00-1 0z"/>',
    },
    {
      key: "config_checksums",
      title: "Config Checksums",
      accent: "--net-accent-slate",
      icon: '<path d="M8 0a8 8 0 100 16A8 8 0 008 0zM2.04 4.326c.325 1.329 2.532 2.54 3.717 3.19.48.263.793.434.743.484-.08.08-.162.158-.242.234-.416.396-.787.749-.758 1.266.035.634.618.824 1.214 1.017.577.188 1.168.38 1.286.983.082.417-.075.988-.22 1.52-.215.782-.406 1.48.22 1.48 1.5-.5 3.798-3.186 4-5 .138-1.243-2-2-3.5-2.5-.478-.16-.755.081-.99.284-.172.15-.322.279-.51.216-.445-.148-2.507-1.388-2.507-1.388z"/>',
    },
    {
      key: "file_modification_checks",
      title: "File Modifications",
      accent: "--net-accent-yellow",
      icon: '<path d="M8 15A7 7 0 118 1a7 7 0 010 14zm0 1A8 8 0 108 0a8 8 0 000 16z"/><path d="M7.002 11a1 1 0 112 0 1 1 0 01-2 0zM7.1 4.995a.905.905 0 111.8 0l-.35 3.507a.552.552 0 01-1.1 0L7.1 4.995z"/>',
    },
  ];

  /* Service state badge helper */
  var SERVICE_STATE_COLOURS = {
    enabled:  "net-svc-enabled",
    disabled: "net-svc-disabled",
    active:   "net-svc-enabled",
    inactive: "net-svc-disabled",
    masked:   "net-svc-disabled",
    "static": "net-svc-neutral",
  };
  function svcBadge(val) {
    var v = String(val || "").trim().toLowerCase();
    var cls = SERVICE_STATE_COLOURS[v] || "net-svc-neutral";
    return '<span class="net-svc-badge ' + cls + '">' + esc(val) + "</span>";
  }

  function renderNetSection(secDef, data, diffMap) {
    var entries = Object.entries(data || {});
    if (!entries.length) return "";
    var accentVar = secDef.accent;
    var isServices = secDef.key === "core_services";
    var isFileList = secDef.key === "file_modification_checks";

    var secDiffCount = 0;
    var rows = entries.map(function (kv) {
      var rawKey = kv[0];
      var rawVal = kv[1];
      var meta = NETWORK_LABELS[rawKey] || {};
      var label = meta.label || rawKey.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
      var unit  = meta.unit || "";

      /* Drift detection */
      var changed = diffMap && diffMap[rawKey];
      var driftHtml = "";
      if (changed) {
        secDiffCount++;
        driftHtml = '<span class="net-drift-badge">CHANGED</span>' +
          '<span class="net-old-value">' + esc(String(changed.old)) + ' → </span>';
      }

      /* Value formatting */
      var valueHtml;
      if (isServices) {
        valueHtml = svcBadge(rawVal);
      } else if (isFileList && Array.isArray(rawVal)) {
        valueHtml = '<ul class="net-file-list">' +
          rawVal.map(function (f) { return '<li><code>' + esc(f) + '</code></li>'; }).join("") +
          '</ul>';
      } else {
        var displayVal = esc(String(rawVal == null ? "—" : rawVal));
        valueHtml = '<span class="net-val">' + displayVal + '</span>';
        if (unit && unit !== "desc") {
          valueHtml += '<span class="net-unit"> ' + esc(unit) + '</span>';
        }
      }

      return (
        '<tr class="' + (changed ? "net-drift-row" : "") + '">' +
        '<td class="net-key-cell"><span class="net-key-label">' + esc(label) + '</span>' +
        '<span class="net-key-raw">' + esc(rawKey) + '</span></td>' +
        '<td class="net-val-cell">' + driftHtml + valueHtml + '</td>' +
        '</tr>'
      );
    }).join("");

    /* Open by default if any property in this card has drifted */
    var isOpen = secDiffCount > 0;
    var driftBadgeHtml = secDiffCount > 0
      ? '<span class="net-sec-drift-badge">' + secDiffCount + ' changed</span>'
      : '';

    return (
      '<div class="net-section-card' + (isOpen ? ' open' : '') + '" style="--sec-accent: var(' + accentVar + ')">' +
      '<div class="net-section-header" title="Click to expand or collapse">' +
      '<svg viewBox="0 0 16 16" fill="currentColor" class="net-sec-icon">' + secDef.icon + '</svg>' +
      '<span class="net-sec-title">' + esc(secDef.title) + '</span>' +
      '<div class="net-sec-meta">' +
      driftBadgeHtml +
      '<span class="net-sec-count">' + entries.length + ' propert' + (entries.length === 1 ? 'y' : 'ies') + '</span>' +
      '<span class="net-sec-chevron">&#9656;</span>' +
      '</div>' +
      '</div>' +
      '<div class="net-section-body">' +
      '<div class="net-section-body-inner">' +
      '<div class="table-wrap">' +
      '<table class="network-table net-rich-table"><tbody>' + rows + '</tbody></table>' +
      '</div></div></div>' +
      '</div>'
    );
  }

  function renderNetworkData() {
    var hasData =
      networkData &&
      Object.keys(networkData).some(function (k) {
        var v = networkData[k];
        return v && typeof v === "object" && Object.keys(v).length > 0;
      });
    var noDataEl = q("networkNoData");
    var contentEl = q("networkContent");
    if (!hasData) {
      if (noDataEl) noDataEl.style.display = "";
      if (contentEl) contentEl.style.display = "none";
      return;
    }
    if (noDataEl) noDataEl.style.display = "none";
    if (contentEl) contentEl.style.display = "";

    /* Collect drift map from threshold data */
    var netDiff = (thresholdData && thresholdData.network_diff) || {};
    var diffMap = netDiff.modified_settings || {};
    var changedCount = Object.keys(diffMap).length;

    /* Drift banner */
    var banner = q("netDriftBanner");
    if (banner) {
      if (changedCount > 0) {
        banner.innerHTML =
          '<svg viewBox="0 0 16 16" fill="currentColor" width="16" height="16"><path d="M8.982 1.566a1.13 1.13 0 00-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 01-1.1 0L7.1 5.995A.905.905 0 018 5zm.002 6a1 1 0 110 2 1 1 0 010-2z"/></svg>' +
          "<strong>" + changedCount + " network propert" + (changedCount === 1 ? "y" : "ies") + " changed</strong>" +
          " since last approved baseline — review rows highlighted in red below.";
        banner.style.display = "flex";
      } else {
        banner.style.display = "none";
      }
    }

    /* Render sections */
    var container = q("netSectionsContainer");
    if (!container) return;
    var visibleCount = 0;
    var html = '<div class="net-sections-grid">';
    NETWORK_SECTIONS.forEach(function (sec) {
      var sectionData = networkData[sec.key];
      if (!sectionData || typeof sectionData !== "object" || !Object.keys(sectionData).length) return;
      visibleCount++;
      /* Per-section diff: match by key in sectionData, explicit section attribute, or NETWORK_LABELS */
      var secDiffMap = {};
      Object.keys(diffMap).forEach(function (k) {
        var d = diffMap[k];
        if (d && d.section === sec.key) {
          secDiffMap[k] = d;
        } else if (Object.prototype.hasOwnProperty.call(sectionData, k)) {
          secDiffMap[k] = d;
        } else {
          var meta = NETWORK_LABELS[k];
          if (meta && meta.section === sec.key) secDiffMap[k] = d;
        }
      });
      html += renderNetSection(sec, sectionData, secDiffMap);
    });
    html += "</div>";
    container.innerHTML = html;

    var catCount = q("netCategoryCount");
    if (catCount) {
      catCount.textContent = visibleCount + " categories";
    }
  }

  /* Network section card expand/collapse toggle */
  document.addEventListener("click", function (e) {
    var hdr = e.target.closest(".net-section-header");
    if (hdr) {
      var card = hdr.closest(".net-section-card");
      if (card) card.classList.toggle("open");
    }
  });

  /* Network toolbar Expand / Collapse All buttons */
  var netExpandBtn = q("netExpandAllBtn");
  if (netExpandBtn) {
    netExpandBtn.addEventListener("click", function () {
      document.querySelectorAll(".net-section-card").forEach(function (c) {
        c.classList.add("open");
      });
    });
  }
  var netCollapseBtn = q("netCollapseAllBtn");
  if (netCollapseBtn) {
    netCollapseBtn.addEventListener("click", function () {
      document.querySelectorAll(".net-section-card").forEach(function (c) {
        c.classList.remove("open");
      });
    });
  }


  /* ── Approval panel ──────────────────────────────────── */
  function _serverIdFromCentralPath() {
    var m = window.location.pathname.match(/^\/server\/([^/]+)\/dashboard/);
    return m ? m[1] : null;
  }

  // Merge rather than replace: thresholdData.reports is seeded from the
  // embedded threshold-data script tag, which reflects the agent's local
  // approval store at generation time — this is the ONLY place a
  // brand-new report's "pending" status exists until a browser decision
  // (approve/reject) registers it into central's separate approvals
  // store. Replacing wholesale would wipe out newly-generated pending
  // reports that central doesn't know about yet, hiding their approval
  // bar entirely. Central's entries still win for any report basename it
  // does know about (i.e. actual decisions).
  function _mergeReportsStatus(newReports) {
    var merged = {};
    var k;
    for (k in thresholdData.reports)
      if (Object.prototype.hasOwnProperty.call(thresholdData.reports, k))
        merged[k] = thresholdData.reports[k];
    for (k in newReports)
      if (Object.prototype.hasOwnProperty.call(newReports, k))
        merged[k] = newReports[k];
    thresholdData.reports = merged;
  }

  function fetchReportStatus() {
    var sid = _serverIdFromCentralPath();
    var url = sid
      ? "/api/server/" + sid + "/report-status"
      : "/api/report-status";
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (d) {
        if (d && d.reports) {
          _mergeReportsStatus(d.reports);
          populateMultiSelect();
          // Restore checkboxes
          var allCbs = els.reportCheckboxes.querySelectorAll(
            'input[type="checkbox"]',
          );
          selectedIndices.forEach(function (i) {
            if (allCbs[i]) allCbs[i].checked = true;
          });
          if (selectedIndices.length) renderMultiple(selectedIndices);
        }
      })
      .catch(function () {});
  }

  window.approveReport = function (basename) {
    if (
      !confirm(
        'Approve report "' + basename + '"? This updates the golden baseline.',
      )
    )
      return;
    var description =
      prompt(
        "Optional: add a note for this approval (reason, ticket #, etc.)",
        "",
      ) || "";
    var sid = _serverIdFromCentralPath();
    var url = sid
      ? "/api/server/" + sid + "/report-approve"
      : "/api/report-approve";
    var meta = (thresholdData.reports || {})[basename] || {};
    var body = {
      report: basename,
      report_label: meta.report_label || basename,
      change_count: meta.change_count || 0,
      threshold:
        meta.threshold != null ? meta.threshold : thresholdData.threshold || 0,
      description: description.trim(),
    };
    if (sid) {
      // Central has no filesystem access to the agent's report file, so
      // include the full report data already loaded client-side.
      var entry = reports.filter(function (r) {
        return r.file && r.file.split("/").pop().split("\\").pop() === basename;
      })[0];
      if (entry) body.report_data = entry.data;
    }
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.success) {
          if (d.status && d.status.reports)
            _mergeReportsStatus(d.status.reports);
          populateMultiSelect();
          var allCbs = els.reportCheckboxes.querySelectorAll(
            'input[type="checkbox"]',
          );
          selectedIndices.forEach(function (i) {
            if (allCbs[i]) allCbs[i].checked = true;
          });
          renderMultiple(selectedIndices);
          showToast(d.message || "Report approved", "success");
        } else showToast(d.message || "Failed", "error");
      })
      .catch(function (e) {
        showToast("Error: " + e.message, "error");
      });
  };

  window.rejectReport = function (basename) {
    if (!confirm('Reject report "' + basename + '"?')) return;
    var description =
      prompt(
        "Optional: add a note for this rejection (reason, ticket #, etc.)",
        "",
      ) || "";
    var sid = _serverIdFromCentralPath();
    var url = sid
      ? "/api/server/" + sid + "/report-reject"
      : "/api/report-reject";
    var meta = (thresholdData.reports || {})[basename] || {};
    var body = {
      report: basename,
      report_label: meta.report_label || basename,
      change_count: meta.change_count || 0,
      threshold:
        meta.threshold != null ? meta.threshold : thresholdData.threshold || 0,
      description: description.trim(),
    };

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.success) {
          if (d.status && d.status.reports)
            _mergeReportsStatus(d.status.reports);
          populateMultiSelect();
          var allCbs = els.reportCheckboxes.querySelectorAll(
            'input[type="checkbox"]',
          );
          selectedIndices.forEach(function (i) {
            if (allCbs[i]) allCbs[i].checked = true;
          });
          renderMultiple(selectedIndices);
          showToast(d.message || "Report rejected", "success");
        } else showToast(d.message || "Failed", "error");
      })
      .catch(function (e) {
        showToast("Error: " + e.message, "error");
      });
  };

  /* ── Snapshot audit ─────────────────────────────────── */
  function snapshotIdForReport(entry) {
    var path = entry && entry.data && entry.data.current_snapshot;
    return path ? path.split("/").pop().split("\\").pop() : "";
  }
  function renderAuditHistory(records) {
    var body =
      (records || [])
        .slice()
        .reverse()
        .map(function (r) {
          var act = (r.action || "").toLowerCase();
          var badgeCls =
            act.indexOf("approve") !== -1
              ? "badge-approve"
              : act.indexOf("reject") !== -1
                ? "badge-reject"
                : "";
          return (
            "<tr>" +
            "<td>" +
            esc(formatDate(r.timestamp)) +
            "</td>" +
            '<td><span class="type-badge ' +
            badgeCls +
            '">' +
            esc(r.action) +
            "</span></td>" +
            '<td class="mono">' +
            esc(formatEntityName(r.snapshot_id)) +
            "</td>" +
            "<td>" +
            esc(r.user) +
            "</td>" +
            "<td>" +
            esc(r.reason) +
            "</td>" +
            "</tr>"
          );
        })
        .join("") ||
      '<tr><td colspan="5" class="net-empty">No approval decisions recorded</td></tr>';
    var auditHistory = q("auditHistory");
    if (auditHistory) auditHistory.innerHTML = body;
    return body;
  }
  function renderDriftAudit(indices) {
    if (!els.driftAuditContent) return;
    if (comparisonMode() || indices.length !== 1) {
      els.driftAuditContent.innerHTML = "";
      return;
    }
    var report = reports[indices[0]].data || {};
    var summary = report.summary || {};
    var fileChanges =
      (summary.added || 0) + (summary.deleted || 0) + (summary.modified || 0);
    var rApp = report.app_diff || thresholdData.app_diff || {};
    var appChanges =
      (rApp.added_apps || []).length +
      (rApp.removed_apps || []).length +
      (rApp.updated_apps || []).length;
    var rNet = report.network_diff || thresholdData.network_diff || {};
    var netChanges = Object.keys(rNet.modified_settings || {}).length;
    var changeCount = fileChanges + appChanges + netChanges;
    var snapshot = snapshotIdForReport(reports[indices[0]]);
    if (!changeCount) {
      els.driftAuditContent.innerHTML = "";
      return;
    }
    if (!snapshot) {
      els.driftAuditContent.innerHTML = "";
      return;
    }
    var sid = _serverIdFromCentralPath();
    var auditUrl = sid
      ? "/api/server/" + sid + "/audit-status"
      : "/api/audit-status";
    fetch(auditUrl)
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (data) {
        var history = renderAuditHistory(data.history);
        var decision = (data.history || [])
          .slice()
          .reverse()
          .find(function (record) {
            return record.snapshot_id === snapshot;
          });
        var isBaseline = !report.previous_snapshot;
        var decisionPanel = "";
        if (decision) {
          var isApproved =
            (decision.action || "").toLowerCase().indexOf("approve") !== -1;
          var statusDot = isApproved ? "dot-added" : "dot-deleted";
          var statusBadge = isApproved
            ? "status-pill approved"
            : "status-pill rejected";
          decisionPanel =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot ' +
            statusDot +
            '"></span>Baseline Decision Recorded</h2>' +
            '<div class="audit-body">' +
            '<div class="audit-decision-row">' +
            '<span class="' +
            statusBadge +
            '">' +
            (isApproved ? "&#10003; " : "&#10007; ") +
            esc(decision.action) +
            "</span>" +
            '<span class="audit-decision-meta">by <strong>' +
            esc(decision.user) +
            "</strong> &bull; " +
            esc(formatDate(decision.timestamp || "")) +
            "</span>" +
            "</div>" +
            '<div class="audit-decision-reason"><span class="audit-reason-label">Reason / Note:</span> ' +
            esc(decision.reason) +
            "</div>" +
            "</div>" +
            "</section>";
        } else if (isBaseline) {
          decisionPanel =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot dot-added"></span>Baseline Decision Recorded</h2>' +
            '<div class="audit-body">' +
            '<div class="audit-decision-row">' +
            '<span class="status-pill approved">&#10003; APPROVED</span>' +
            '<span class="audit-decision-meta">by <strong>system (initial baseline)</strong>' +
            (report.generated_at
              ? " &bull; " + esc(formatDate(report.generated_at))
              : "") +
            "</span>" +
            "</div>" +
            '<div class="audit-decision-reason"><span class="audit-reason-label">Reason / Note:</span> Auto-approved initial baseline</div>' +
            "</div>" +
            "</section>";
        } else {
          decisionPanel =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Baseline Approval</h2>' +
            '<div class="audit-body">' +
            '<p class="audit-caption"><span class="audit-warn-count">' +
            changeCount +
            ' detected change(s)</span> in snapshot <span class="mono audit-snapshot-tag">' +
            esc(formatEntityName(snapshot)) +
            "</span></p>" +
            '<div class="config-form audit-controls">' +
            '<div class="form-group">' +
            '<label for="driftApprover">Approver Name <span class="req">*</span></label>' +
            '<input type="text" id="driftApprover" autocomplete="name" placeholder="e.g. John Doe / Team Lead" required>' +
            "</div>" +
            '<div class="form-group">' +
            '<label for="driftReason">Reason / Ticket Note <span class="req">*</span></label>' +
            '<input type="text" id="driftReason" placeholder="e.g. Approved update / Ticket #1234" required>' +
            "</div>" +
            "</div>" +
            '<div class="config-actions audit-actions">' +
            '<button type="button" id="rejectDriftSnapshotBtn" class="btn btn-secondary btn-reject-alt">&#10007; Reject Changes</button>' +
            '<button type="button" id="approveDriftSnapshotBtn" class="btn btn-primary btn-approve-alt">&#10003; Approve and Update Baseline</button>' +
            "</div>" +
            "</div>" +
            "</section>";
        }
        els.driftAuditContent.innerHTML =
          decisionPanel +
          '<section class="panel audit-panel">' +
          '<h2 class="panel-title"><span class="panel-dot dot-dash"></span>Approval Pipeline</h2>' +
          '<div class="table-wrap"><table class="network-table"><thead><tr><th>Timestamp</th><th>Action</th><th>Snapshot ID</th><th>User / Approver</th><th>Reason / Note</th></tr></thead><tbody>' +
          history +
          "</tbody></table></div>" +
          "</section>";
        if (!decision && !isBaseline) {
          q("approveDriftSnapshotBtn").addEventListener("click", function () {
            decideSnapshot("approve", snapshot);
          });
          q("rejectDriftSnapshotBtn").addEventListener("click", function () {
            decideSnapshot("reject", snapshot);
          });
        }
      })
      .catch(function () {
        els.driftAuditContent.innerHTML = "";
      });
  }
  function decideSnapshot(action, snapshot) {
    var user = q("driftApprover").value.trim(),
      reason = q("driftReason").value.trim();
    if (!user || !reason) {
      showToast("Approver name and reason are required", "error");
      return;
    }
    var sid = _serverIdFromCentralPath();
    var decisionUrl = sid
      ? "/api/server/" + sid + "/snapshot-" + action
      : "/api/snapshot-" + action;
    fetch(decisionUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot: snapshot, user: user, reason: reason }),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.error || "Decision failed");
          return d;
        });
      })
      .then(function (d) {
        renderAuditHistory(d.history);
        showToast("Snapshot " + action + " recorded", "success");
        if (selectedIndices.length === 1) renderDriftAudit(selectedIndices);
        updateTabBadges();
      })
      .catch(function (e) {
        showToast(e.message, "error");
      });
  }

  /* ── Tab Badges & Baseline Deciders (App & Network) ───── */
  function updateTabBadges() {
    var repCount = 0;
    if (selectedIndices && selectedIndices.length === 1) {
      var r = reports[selectedIndices[0]].data || {};
      var s = r.summary || {};
      var fc = (s.added || 0) + (s.deleted || 0) + (s.modified || 0);
      var rApp = r.app_diff || thresholdData.app_diff || {};
      var ac =
        (rApp.added_apps || []).length +
        (rApp.removed_apps || []).length +
        (rApp.updated_apps || []).length;
      var rNet = r.network_diff || thresholdData.network_diff || {};
      var nc = Object.keys(rNet.modified_settings || {}).length;
      repCount = fc + ac + nc;
    } else if (selectedIndices && selectedIndices.length > 1) {
      selectedIndices.forEach(function (idx) {
        var r = reports[idx].data || {};
        var s = r.summary || {};
        repCount += (s.added || 0) + (s.deleted || 0) + (s.modified || 0);
      });
    } else if (reports.length > 0) {
      var lastR = reports[reports.length - 1].data || {};
      var s = lastR.summary || {};
      var fc = (s.added || 0) + (s.deleted || 0) + (s.modified || 0);
      var rApp = lastR.app_diff || thresholdData.app_diff || {};
      var ac =
        (rApp.added_apps || []).length +
        (rApp.removed_apps || []).length +
        (rApp.updated_apps || []).length;
      var rNet = lastR.network_diff || thresholdData.network_diff || {};
      var nc = Object.keys(rNet.modified_settings || {}).length;
      repCount = fc + ac + nc;
    }
    var bRep = q("badge-reports");
    if (bRep) {
      if (repCount > 0) {
        bRep.textContent = repCount;
        bRep.style.display = "inline-flex";
      } else {
        bRep.style.display = "none";
      }
    }

    var appDiff = (thresholdData && thresholdData.app_diff) || {};
    if (
      !appDiff.category &&
      reports.length &&
      reports[reports.length - 1].data.app_diff
    ) {
      appDiff = reports[reports.length - 1].data.app_diff;
    }
    var appTotal =
      (appDiff.added_apps || []).length +
      (appDiff.removed_apps || []).length +
      (appDiff.updated_apps || []).length;
    var bApp = q("badge-app");
    if (bApp) {
      if (appTotal > 0) {
        bApp.textContent = appTotal;
        bApp.style.display = "inline-flex";
      } else {
        bApp.style.display = "none";
      }
    }

    var netDiff = (thresholdData && thresholdData.network_diff) || {};
    if (
      !netDiff.category &&
      reports.length &&
      reports[reports.length - 1].data.network_diff
    ) {
      netDiff = reports[reports.length - 1].data.network_diff;
    }
    var netTotal = Object.keys(netDiff.modified_settings || {}).length;
    var bNet = q("badge-network");
    if (bNet) {
      if (netTotal > 0) {
        bNet.textContent = netTotal;
        bNet.style.display = "inline-flex";
      } else {
        bNet.style.display = "none";
      }
    }
  }

  function renderAppAudit() {
    var cont = q("appAuditContent");
    if (!cont) return;
    var appDiff = (thresholdData && thresholdData.app_diff) || {};
    if (
      !appDiff.category &&
      reports.length &&
      reports[reports.length - 1].data.app_diff
    ) {
      appDiff = reports[reports.length - 1].data.app_diff;
    }
    var added = (appDiff.added_apps || []).length;
    var removed = (appDiff.removed_apps || []).length;
    var updated = (appDiff.updated_apps || []).length;
    var totalAppChanges = added + removed + updated;

    if (!totalAppChanges) {
      cont.innerHTML = "";
      return;
    }

    var sid = _serverIdFromCentralPath();
    var statusUrl = sid ? "/api/server/" + sid + "/status" : "/api/status";

    fetch(statusUrl)
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (data) {
        var catStatus = (data.categories && data.categories.app) || {};
        var isApproved = catStatus.status === "approved";
        var isRejected = catStatus.status === "rejected";

        if (isApproved || isRejected) {
          var statusDot = isApproved ? "dot-added" : "dot-deleted";
          var statusBadge = isApproved
            ? "status-pill approved"
            : "status-pill rejected";
          cont.innerHTML =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot ' +
            statusDot +
            '"></span>Application Baseline Decision Recorded</h2>' +
            '<div class="audit-body">' +
            '<div class="audit-decision-row">' +
            '<span class="' +
            statusBadge +
            '">' +
            (isApproved ? "&#10003; APPROVED" : "&#10007; REJECTED") +
            "</span>" +
            '<span class="audit-decision-meta">' +
            (catStatus.timestamp
              ? " &bull; " + esc(formatDate(catStatus.timestamp))
              : "") +
            "</span>" +
            "</div>" +
            "</div>" +
            "</section>";
        } else {
          cont.innerHTML =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Application Baseline Approval</h2>' +
            '<div class="audit-body">' +
            '<p class="audit-caption"><span class="audit-warn-count">' +
            totalAppChanges +
            " detected binary/script change(s)</span> vs approved baseline (" +
            added +
            " added, " +
            removed +
            " removed, " +
            updated +
            " updated)</p>" +
            '<div class="config-form audit-controls">' +
            '<div class="form-group">' +
            '<label for="appApprover">Approver Name <span class="req">*</span></label>' +
            '<input type="text" id="appApprover" autocomplete="name" placeholder="e.g. John Doe / Team Lead" required>' +
            "</div>" +
            '<div class="form-group">' +
            '<label for="appReason">Reason / Ticket Note <span class="req">*</span></label>' +
            '<input type="text" id="appReason" placeholder="e.g. Approved binary upgrade / Ticket #1234" required>' +
            "</div>" +
            "</div>" +
            '<div class="config-actions audit-actions">' +
            '<button type="button" id="rejectAppBaselineBtn" class="btn btn-secondary btn-reject-alt">&#10007; Reject Changes</button>' +
            '<button type="button" id="approveAppBaselineBtn" class="btn btn-primary btn-approve-alt">&#10003; Approve and Update Baseline</button>' +
            "</div>" +
            "</div>" +
            "</section>";

          var btnApprove = q("approveAppBaselineBtn");
          if (btnApprove) {
            btnApprove.addEventListener("click", function () {
              var user = (
                q("appApprover") ? q("appApprover").value : ""
              ).trim();
              var reason = (q("appReason") ? q("appReason").value : "").trim();
              decideCategoryBaseline("app", "approve", appData, user, reason);
            });
          }
          var btnReject = q("rejectAppBaselineBtn");
          if (btnReject) {
            btnReject.addEventListener("click", function () {
              var user = (
                q("appApprover") ? q("appApprover").value : ""
              ).trim();
              var reason = (q("appReason") ? q("appReason").value : "").trim();
              decideCategoryBaseline("app", "reject", {}, user, reason);
            });
          }
        }
      })
      .catch(function () {
        cont.innerHTML =
          '<section class="panel audit-panel">' +
          '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Application Baseline Approval</h2>' +
          '<div class="audit-body">' +
          '<p class="audit-caption"><span class="audit-warn-count">' +
          totalAppChanges +
          " detected binary/script change(s)</span> vs approved baseline</p>" +
          '<div class="config-form audit-controls">' +
          '<div class="form-group">' +
          '<label for="appApprover">Approver Name <span class="req">*</span></label>' +
          '<input type="text" id="appApprover" autocomplete="name" placeholder="e.g. John Doe / Team Lead" required>' +
          "</div>" +
          '<div class="form-group">' +
          '<label for="appReason">Reason / Ticket Note <span class="req">*</span></label>' +
          '<input type="text" id="appReason" placeholder="e.g. Approved binary upgrade / Ticket #1234" required>' +
          "</div>" +
          "</div>" +
          '<div class="config-actions audit-actions">' +
          '<button type="button" id="rejectAppBaselineBtn" class="btn btn-secondary btn-reject-alt">&#10007; Reject Changes</button>' +
          '<button type="button" id="approveAppBaselineBtn" class="btn btn-primary btn-approve-alt">&#10003; Approve and Update Baseline</button>' +
          "</div>" +
          "</div>" +
          "</section>";
        var btnApprove = q("approveAppBaselineBtn");
        if (btnApprove) {
          btnApprove.addEventListener("click", function () {
            var user = (q("appApprover") ? q("appApprover").value : "").trim();
            var reason = (q("appReason") ? q("appReason").value : "").trim();
            decideCategoryBaseline("app", "approve", appData, user, reason);
          });
        }
        var btnReject = q("rejectAppBaselineBtn");
        if (btnReject) {
          btnReject.addEventListener("click", function () {
            var user = (q("appApprover") ? q("appApprover").value : "").trim();
            var reason = (q("appReason") ? q("appReason").value : "").trim();
            decideCategoryBaseline("app", "reject", {}, user, reason);
          });
        }
      });
  }

  function renderNetworkAudit() {
    var cont = q("netAuditContent");
    if (!cont) return;
    var netDiff = (thresholdData && thresholdData.network_diff) || {};
    if (
      !netDiff.category &&
      reports.length &&
      reports[reports.length - 1].data.network_diff
    ) {
      netDiff = reports[reports.length - 1].data.network_diff;
    }
    var totalNetChanges = Object.keys(netDiff.modified_settings || {}).length;

    if (!totalNetChanges) {
      cont.innerHTML = "";
      return;
    }

    var sid = _serverIdFromCentralPath();
    var statusUrl = sid ? "/api/server/" + sid + "/status" : "/api/status";

    fetch(statusUrl)
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (data) {
        var catStatus = (data.categories && data.categories.network) || {};
        var isApproved = catStatus.status === "approved";
        var isRejected = catStatus.status === "rejected";

        if (isApproved || isRejected) {
          var statusDot = isApproved ? "dot-added" : "dot-deleted";
          var statusBadge = isApproved
            ? "status-pill approved"
            : "status-pill rejected";
          cont.innerHTML =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot ' +
            statusDot +
            '"></span>Network Baseline Decision Recorded</h2>' +
            '<div class="audit-body">' +
            '<div class="audit-decision-row">' +
            '<span class="' +
            statusBadge +
            '">' +
            (isApproved ? "&#10003; APPROVED" : "&#10007; REJECTED") +
            "</span>" +
            '<span class="audit-decision-meta">' +
            (catStatus.timestamp
              ? " &bull; " + esc(formatDate(catStatus.timestamp))
              : "") +
            "</span>" +
            "</div>" +
            "</div>" +
            "</section>";
        } else {
          cont.innerHTML =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Network Baseline Approval</h2>' +
            '<div class="audit-body">' +
            '<p class="audit-caption"><span class="audit-warn-count">' +
            totalNetChanges +
            " detected network configuration change(s)</span> vs approved baseline</p>" +
            '<div class="config-form audit-controls">' +
            '<div class="form-group">' +
            '<label for="netApprover">Approver Name <span class="req">*</span></label>' +
            '<input type="text" id="netApprover" autocomplete="name" placeholder="e.g. John Doe / Team Lead" required>' +
            "</div>" +
            '<div class="form-group">' +
            '<label for="netReason">Reason / Ticket Note <span class="req">*</span></label>' +
            '<input type="text" id="netReason" placeholder="e.g. Scheduled network maintenance / Ticket #1234" required>' +
            "</div>" +
            "</div>" +
            '<div class="config-actions audit-actions">' +
            '<button type="button" id="rejectNetBaselineBtn" class="btn btn-secondary btn-reject-alt">&#10007; Reject Changes</button>' +
            '<button type="button" id="approveNetBaselineBtn" class="btn btn-primary btn-approve-alt">&#10003; Approve and Update Baseline</button>' +
            "</div>" +
            "</div>" +
            "</section>";

          var btnApprove = q("approveNetBaselineBtn");
          if (btnApprove) {
            btnApprove.addEventListener("click", function () {
              var user = (
                q("netApprover") ? q("netApprover").value : ""
              ).trim();
              var reason = (q("netReason") ? q("netReason").value : "").trim();
              decideCategoryBaseline(
                "network",
                "approve",
                networkData,
                user,
                reason,
              );
            });
          }
          var btnReject = q("rejectNetBaselineBtn");
          if (btnReject) {
            btnReject.addEventListener("click", function () {
              var user = (
                q("netApprover") ? q("netApprover").value : ""
              ).trim();
              var reason = (q("netReason") ? q("netReason").value : "").trim();
              decideCategoryBaseline("network", "reject", {}, user, reason);
            });
          }
        }
      })
      .catch(function () {
        cont.innerHTML =
          '<section class="panel audit-panel">' +
          '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Network Baseline Approval</h2>' +
          '<div class="audit-body">' +
          '<p class="audit-caption"><span class="audit-warn-count">' +
          totalNetChanges +
          " detected network configuration change(s)</span> vs approved baseline</p>" +
          '<div class="config-form audit-controls">' +
          '<div class="form-group">' +
          '<label for="netApprover">Approver Name <span class="req">*</span></label>' +
          '<input type="text" id="netApprover" autocomplete="name" placeholder="e.g. John Doe / Team Lead" required>' +
          "</div>" +
          '<div class="form-group">' +
          '<label for="netReason">Reason / Ticket Note <span class="req">*</span></label>' +
          '<input type="text" id="netReason" placeholder="e.g. Scheduled network maintenance / Ticket #1234" required>' +
          "</div>" +
          "</div>" +
          '<div class="config-actions audit-actions">' +
          '<button type="button" id="rejectNetBaselineBtn" class="btn btn-secondary btn-reject-alt">&#10007; Reject Changes</button>' +
          '<button type="button" id="approveNetBaselineBtn" class="btn btn-primary btn-approve-alt">&#10003; Approve and Update Baseline</button>' +
          "</div>" +
          "</div>" +
          "</section>";
        var btnApprove = q("approveNetBaselineBtn");
        if (btnApprove) {
          btnApprove.addEventListener("click", function () {
            var user = (q("netApprover") ? q("netApprover").value : "").trim();
            var reason = (q("netReason") ? q("netReason").value : "").trim();
            decideCategoryBaseline(
              "network",
              "approve",
              networkData,
              user,
              reason,
            );
          });
        }
        var btnReject = q("rejectNetBaselineBtn");
        if (btnReject) {
          btnReject.addEventListener("click", function () {
            var user = (q("netApprover") ? q("netApprover").value : "").trim();
            var reason = (q("netReason") ? q("netReason").value : "").trim();
            decideCategoryBaseline("network", "reject", {}, user, reason);
          });
        }
      });
  }

  function decideCategoryBaseline(
    category,
    action,
    snapshotData,
    user,
    reason,
  ) {
    if (!user || !reason) {
      showToast("Approver name and reason are required", "error");
      return;
    }
    var sid = _serverIdFromCentralPath();
    var url = sid ? "/api/server/" + sid + "/" + action : "/api/" + action;

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category: category,
        snapshot_data: snapshotData,
        user: user,
        reason: reason,
      }),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok)
            throw new Error(d.error || category + " " + action + " failed");
          return d;
        });
      })
      .then(function (d) {
        showToast(
          (category === "app" ? "Application" : "Network") +
            " baseline " +
            action +
            "d successfully",
          "success",
        );
        if (category === "app") {
          renderAppAudit();
          if (action === "approve") {
            if (thresholdData.app_diff) thresholdData.app_diff = {};
          }
        } else if (category === "network") {
          renderNetworkAudit();
          if (action === "approve") {
            if (thresholdData.network_diff) thresholdData.network_diff = {};
            var banner = q("netDriftBanner");
            if (banner) banner.style.display = "none";
          }
        }
        updateTabBadges();
      })
      .catch(function (e) {
        showToast(e.message, "error");
      });
  }

  /* ── Config CRUD ─────────────────────────────────────── */
  var _isCentralMode = !!window.location.pathname.match(
    /^\/server\/([^/]+)\/dashboard/,
  );
  function loadConfig() {
    var url = "/api/config";
    var match = window.location.pathname.match(/^\/server\/([^/]+)\/dashboard/);
    if (match) url = "/api/server/" + match[1] + "/config";
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (d) {
        if (d.error) throw new Error(d.error);
        configData = d;
        q("configUnavailable").style.display = "none";
        q("configContent").style.display = "";
        // Show the central-mode banner when served via central platform.
        if (_isCentralMode) q("centralConfigBanner").style.display = "";
        populateConfigForm(d);
      })
      .catch(function () {
        q("configUnavailable").style.display = "";
        q("configContent").style.display = "none";
      });
  }
  function populateConfigForm(cfg) {
    var match = window.location.pathname.match(/^\/server\/([^/]+)\/dashboard/);
    var defaultServerId = match ? match[1] : "";
    q("cfgServerId").value = cfg.server_id || defaultServerId;
    q("cfgHostname").value = cfg.hostname || "";
    q("cfgSnapshotDir").value =
      cfg.snapshot_dir || "/else/serversnap/snapshots";
    q("cfgReportDir").value = cfg.report_dir || "/else/serversnap/reports";
    q("cfgLogFile").value =
      cfg.log_file || "/else/serversnap/logs/server_snapshot.log";
    q("cfgMaxContentSize").value = cfg.max_content_size_bytes || 5242880;
    q("cfgRetentionCount").value =
      cfg.retention_count != null ? cfg.retention_count : 30;
    q("cfgChangeThreshold").value =
      cfg.change_threshold != null ? cfg.change_threshold : 0;
    var al = cfg.alerting || {};
    q("cfgAlertCommand").value = al.command || "";
    q("cfgWebhookUrl").value = al.webhook_url || "";
    var db = cfg.dashboard || {};
    q("cfgDashHost").value = db.host || "127.0.0.1";
    q("cfgDashPort").value = db.port || 8080;

    var paths = cfg.paths || [];
    if (paths.length === 0) {
      paths = [{ path: "/etc", include_content: false, recursive: true }];
      if (configData) configData.paths = paths;
    }

    // Cross-reference paths against snapshot data to annotate missing entries.
    // `reports` is the global list from the embedded JSON; use the latest entry's snapshot.
    try {
      var latestEntries = reports.length
        ? (reports[reports.length - 1].data.snapshot || {}).entries || {}
        : {};
      paths = paths.map(function (p) {
        var entry = latestEntries[p.path];
        if (entry && entry.type === "missing") {
          return Object.assign({}, p, { _missing: true });
        }
        return p;
      });
    } catch (e) {
      /* non-fatal */
    }

    renderPaths(paths);
    renderUncoveredPathsBanner(paths);
  }
  /* Cross-reference the latest report's changed files against the monitored
       paths list, so users understand why a changed file (e.g. shown under
       "Drift Reports") may not appear as its own entry here — either it's
       nested inside an existing recursive path (expected), or it truly isn't
       covered by any monitored path yet (flagged below, with a quick fix). */
  function getChangedPathsFromLatestReport() {
    if (!reports.length) return [];
    var r = reports[reports.length - 1].data || {};
    var out = [];
    ["added", "deleted", "modified"].forEach(function (key) {
      (r[key] || []).forEach(function (x) {
        var p = typeof x === "string" ? x : x && x.path;
        if (p) out.push(p);
      });
    });
    return out;
  }
  function isPathCovered(changedPath, cfgPath) {
    var base = cfgPath && cfgPath.path;
    if (!base) return false;
    if (changedPath === base) return true;
    if (cfgPath.recursive === false) {
      // Non-recursive: only direct children of base are covered.
      var lastSlash = changedPath.lastIndexOf("/");
      var parent = lastSlash > 0 ? changedPath.slice(0, lastSlash) : "/";
      return parent === base;
    }
    // Recursive (default): anything under base/ is covered.
    return changedPath.indexOf(base.replace(/\/$/, "") + "/") === 0;
  }
  function renderUncoveredPathsBanner(paths) {
    var banner = q("uncoveredPathsBanner");
    if (!banner) return;
    var changed = getChangedPathsFromLatestReport();
    var uncovered = [];
    changed.forEach(function (cp) {
      if (
        uncovered.indexOf(cp) === -1 &&
        !paths.some(function (p) {
          return isPathCovered(cp, p);
        })
      ) {
        uncovered.push(cp);
      }
    });
    if (!uncovered.length) {
      banner.style.display = "none";
      banner.innerHTML = "";
      return;
    }
    banner.style.display = "";
    banner.innerHTML =
      '<div class="config-uncovered-banner__title">&#9888; ' +
      uncovered.length +
      " changed path" +
      (uncovered.length > 1 ? "s" : "") +
      " from the latest report " +
      (uncovered.length > 1 ? "aren't" : "isn't") +
      " covered by any monitored path below. The report may have been generated with a " +
      "different config than what\u2019s currently loaded, or these need to be added.</div>" +
      uncovered
        .map(function (p) {
          return (
            '<div class="config-uncovered-banner__row"><span>' +
            esc(p) +
            "</span>" +
            '<button type="button" class="btn btn-xs btn-secondary add-uncovered-btn" data-path="' +
            esc(p) +
            '">+ Add</button></div>'
          );
        })
        .join("");
  }
  q("uncoveredPathsBanner") &&
    q("uncoveredPathsBanner").addEventListener("click", function (e) {
      var btn = e.target.closest(".add-uncovered-btn");
      if (!btn) return;
      openPathModal(-1);
      q("modalPath").value = btn.getAttribute("data-path") || "";
    });
  function gatherConfigFromForm() {
    var cfg = {};
    cfg.server_id = q("cfgServerId").value.trim();
    var hn = q("cfgHostname").value.trim();
    if (hn) cfg.hostname = hn;
    cfg.snapshot_dir = q("cfgSnapshotDir").value.trim();
    cfg.report_dir = q("cfgReportDir").value.trim();
    var lf = q("cfgLogFile").value.trim();
    if (lf) cfg.log_file = lf;
    cfg.max_content_size_bytes =
      parseInt(q("cfgMaxContentSize").value, 10) || 5242880;
    cfg.retention_count = parseInt(q("cfgRetentionCount").value, 10);
    if (isNaN(cfg.retention_count)) cfg.retention_count = 30;
    cfg.change_threshold = parseInt(q("cfgChangeThreshold").value, 10);
    if (isNaN(cfg.change_threshold)) cfg.change_threshold = 0;
    cfg.paths = configData && configData.paths ? configData.paths : [];
    var ac = q("cfgAlertCommand").value.trim();
    var wu = q("cfgWebhookUrl").value.trim();
    cfg.alerting = { command: ac || null, webhook_url: wu || null };
    cfg.dashboard = {
      host: q("cfgDashHost").value.trim() || "127.0.0.1",
      port: parseInt(q("cfgDashPort").value, 10) || 8080,
    };
    return cfg;
  }
  function saveConfig() {
    var cfg = gatherConfigFromForm();
    if (!cfg.server_id) {
      showToast("Server ID is required", "error");
      return;
    }
    if (!cfg.snapshot_dir || !cfg.snapshot_dir.startsWith("/")) {
      showToast("Snapshot dir must be an absolute path", "error");
      return;
    }
    if (!cfg.report_dir || !cfg.report_dir.startsWith("/")) {
      showToast("Report dir must be an absolute path", "error");
      return;
    }
    if (!cfg.paths || !cfg.paths.length) {
      showToast("At least one monitored path required", "error");
      return;
    }
    var btn = q("saveConfigBtn");
    btn.disabled = true;
    btn.textContent = "Saving\u2026";
    var url = "/api/config";
    var method = "PUT";
    var match = window.location.pathname.match(/^\/server\/([^/]+)\/dashboard/);
    if (match) {
      url = "/api/server/" + match[1] + "/config";
      method = "POST";
    }
    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.error) {
          var detail =
            d.details && d.details.length ? "\n" + d.details.join("\n") : "";
          showToast(d.error + detail, "error");
        } else {
          configData = cfg;
          var msg = _isCentralMode
            ? d.message ||
              "Config queued \u2014 will be applied on agent\u2019s next run"
            : d.message || "Configuration saved";
          showToast(msg, "success");
        }
      })
      .catch(function (e) {
        showToast("Failed to save: " + e.message, "error");
      })
      .finally(function () {
        btn.disabled = false;
        btn.innerHTML = "\u{1F4BE} Save Configuration";
      });
  }
  function renderPaths(paths) {
    var container = q("pathsList");
    var emptyEl = q("pathsEmpty");
    if (!paths || !paths.length) {
      container.innerHTML = "";
      emptyEl.style.display = "";
      return;
    }
    emptyEl.style.display = "none";
    container.innerHTML = paths
      .map(function (p, i) {
        var exc = (p.exceptions || []).length;
        var tags = [];
        if (p.recursive !== false) tags.push("recursive");
        if (p.include_content) tags.push("content");
        if (exc) tags.push(exc + " exception" + (exc > 1 ? "s" : ""));
        // If the snapshot entry for this path is missing, show a warning indicator.
        var isMissing = p._missing === true;
        var missingBadge = isMissing
          ? '<span class="path-tag path-tag--warn" title="This path does not exist on the agent server yet">⚠ not on disk</span>'
          : "";
        return (
          '<div class="path-card' +
          (isMissing ? " path-card--missing" : "") +
          '" data-path-index="' +
          i +
          '">' +
          '<div class="path-card-header">' +
          '<span class="path-card-path">' +
          esc(p.path) +
          "</span>" +
          '<div class="path-card-actions">' +
          '<button type="button" class="btn btn-xs btn-secondary edit-path-btn" data-index="' +
          i +
          '">Edit</button>' +
          '<button type="button" class="btn btn-xs btn-danger delete-path-btn" data-index="' +
          i +
          '">Delete</button>' +
          "</div></div>" +
          '<div class="path-card-meta">' +
          tags
            .map(function (t) {
              return '<span class="path-tag">' + esc(t) + "</span>";
            })
            .join("") +
          missingBadge +
          "</div>" +
          "</div>"
        );
      })
      .join("");
  }
  q("pathsList").addEventListener("click", function (e) {
    var eb = e.target.closest(".edit-path-btn");
    var db = e.target.closest(".delete-path-btn");
    if (eb) openPathModal(parseInt(eb.getAttribute("data-index"), 10));
    if (db) deletePath(parseInt(db.getAttribute("data-index"), 10));
  });
  function openPathModal(idx) {
    editingPathIdx = idx;
    var modal = q("pathModal");
    var title = q("pathModalTitle");
    if (idx >= 0 && configData && configData.paths && configData.paths[idx]) {
      title.textContent = "Edit Monitored Path";
      var p = configData.paths[idx];
      q("modalPath").value = p.path || "";
      q("modalRecursive").checked = p.recursive !== false;
      q("modalIncludeContent").checked = !!p.include_content;
      renderExceptions(p.exceptions || []);
    } else {
      title.textContent = "Add Monitored Path";
      q("modalPath").value = "";
      q("modalRecursive").checked = true;
      q("modalIncludeContent").checked = false;
      renderExceptions([]);
    }
    modal.style.display = "flex";
  }
  function closePathModal() {
    q("pathModal").style.display = "none";
    editingPathIdx = -1;
  }
  function savePathModal() {
    var pv = q("modalPath").value.trim();
    if (!pv) {
      showToast("Path is required", "error");
      return;
    }
    if (!pv.startsWith("/")) {
      showToast("Path must be absolute (start with /)", "error");
      return;
    }
    var entry = {
      path: pv,
      recursive: q("modalRecursive").checked,
      include_content: q("modalIncludeContent").checked,
    };
    var excRows = document.querySelectorAll("#modalExceptions .exception-row");
    var exceptions = [];
    excRows.forEach(function (row) {
      var ep = row.querySelector(".exc-path").value.trim();
      var eg = row.querySelector(".exc-pattern").value.trim();
      var ec = row.querySelector(".exc-content").checked;
      var esk = row.querySelector(".exc-skip").checked;
      if (ep || eg) {
        var exc = { include_content: ec, skip: esk };
        if (ep) exc.path = ep;
        else exc.pattern = eg;
        exceptions.push(exc);
      }
    });
    if (exceptions.length) entry.exceptions = exceptions;
    if (!configData) configData = { paths: [] };
    if (!configData.paths) configData.paths = [];
    if (editingPathIdx >= 0) {
      configData.paths[editingPathIdx] = entry;
      showToast("Path updated (save to persist)", "info");
    } else {
      configData.paths.push(entry);
      showToast("Path added (save to persist)", "info");
    }
    renderPaths(configData.paths);
    closePathModal();
  }
  function deletePath(idx) {
    if (!configData || !configData.paths || !configData.paths[idx]) return;
    var pn = configData.paths[idx].path;
    if (!confirm("Delete monitored path: " + pn + "?")) return;
    configData.paths.splice(idx, 1);
    renderPaths(configData.paths);
    showToast("Path removed (save to persist)", "info");
  }
  function renderExceptions(exc) {
    q("modalExceptions").innerHTML = (exc || [])
      .map(function (e) {
        return (
          '<div class="exception-row">' +
          '<input type="text" class="exc-path" placeholder="Exact path (e.g. /etc/nginx/cache)" value="' +
          esc(e.path || "") +
          '">' +
          '<input type="text" class="exc-pattern" placeholder="Glob (e.g. /etc/nginx/**/*.bak)" value="' +
          esc(e.pattern || "") +
          '">' +
          '<label class="toggle-label exc-skip-label" title="Skip: fully exclude from monitoring">' +
          '<input type="checkbox" class="exc-skip"' +
          (e.skip ? " checked" : "") +
          ">Skip</label>" +
          '<label class="toggle-label">' +
          '<input type="checkbox" class="exc-content"' +
          (e.include_content ? " checked" : "") +
          ">Content</label>" +
          '<button type="button" class="btn btn-xs btn-danger remove-exc-btn">&times;</button>' +
          "</div>"
        );
      })
      .join("");
  }
  function addException() {
    var c = q("modalExceptions");
    var r = document.createElement("div");
    r.className = "exception-row";
    r.innerHTML =
      '<input type="text" class="exc-path" placeholder="Exact path (e.g. /etc/nginx/cache)">' +
      '<input type="text" class="exc-pattern" placeholder="Glob (e.g. /etc/nginx/**/*.bak)">' +
      '<label class="toggle-label exc-skip-label" title="Skip: fully exclude from monitoring"><input type="checkbox" class="exc-skip">Skip</label>' +
      '<label class="toggle-label"><input type="checkbox" class="exc-content">Content</label>' +
      '<button type="button" class="btn btn-xs btn-danger remove-exc-btn">&times;</button>';
    c.appendChild(r);
  }
  q("addPathBtn").addEventListener("click", function () {
    openPathModal(-1);
  });
  q("pathModalSave").addEventListener("click", savePathModal);
  q("pathModalCancel").addEventListener("click", closePathModal);
  q("pathModalClose").addEventListener("click", closePathModal);
  q("addExceptionBtn").addEventListener("click", addException);
  q("pathModal").addEventListener("click", function (e) {
    if (e.target === this) closePathModal();
  });
  q("modalExceptions").addEventListener("click", function (e) {
    var btn = e.target.closest(".remove-exc-btn");
    if (btn) {
      var row = btn.closest(".exception-row");
      if (row && row.parentNode) row.parentNode.removeChild(row);
    }
  });
  q("saveConfigBtn").addEventListener("click", saveConfig);
  q("reloadConfigBtn").addEventListener("click", function () {
    configData = null;
    loadConfig();
    showToast("Configuration reloaded", "info");
  });

  /* ── Init ────────────────────────────────────────────── */
  if (!reports.length) {
    els.subtitle.textContent = "No report data available";
    q("emptyState").style.display = "";
  } else {
    populateMultiSelect();
    var allCbs = els.reportCheckboxes.querySelectorAll(
      'input[type="checkbox"]',
    );
    if (allCbs.length) allCbs[allCbs.length - 1].checked = true;
    selectedIndices = getSelectedIndices();
    updateTriggerText();
    renderMultiple(selectedIndices);
  }

  updateTabBadges();
  renderAppAudit();
  renderNetworkAudit();

  fetchReportStatus();
  setInterval(fetchReportStatus, 30000);
})();
