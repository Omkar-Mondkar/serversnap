// (function () {
//   "use strict";

//   /* ── Data ────────────────────────────────────────────── */
//   var reports = JSON.parse(
//     document.getElementById("report-data").textContent || "[]",
//   );
//   var appData = JSON.parse(
//     (document.getElementById("app-data") || { textContent: "{}" })
//       .textContent || "{}",
//   );
//   var networkData = JSON.parse(
//     (document.getElementById("network-data") || { textContent: "{}" })
//       .textContent || "{}",
//   );
//   var thresholdData = JSON.parse(
//     (document.getElementById("threshold-data") || { textContent: "{}" })
//       .textContent || "{}",
//   );
//   var selectedIndices = [];
//   var configData = null;
//   var editingPathIdx = -1;

//   /* ── Element cache ───────────────────────────────────── */
//   function q(id) {
//     return document.getElementById(id);
//   }
//   var els = {
//     subtitle: q("subtitle"),
//     metaServerId: q("metaServerId"),
//     metaHostname: q("metaHostname"),
//     metaGenerated: q("metaGenerated"),
//     metaPrev: q("metaPrev"),
//     metaCurr: q("metaCurr"),
//     countAdded: q("countAdded"),
//     countDeleted: q("countDeleted"),
//     countModified: q("countModified"),
//     countUnchanged: q("countUnchanged"),
//     segAdded: document.querySelector(".seg-added"),
//     segDeleted: document.querySelector(".seg-deleted"),
//     segModified: document.querySelector(".seg-modified"),
//     segUnchanged: document.querySelector(".seg-unchanged"),
//     driftTopContent: q("driftTopContent"),
//     driftAuditContent: q("driftAuditContent"),
//     emptyState: q("emptyState"),
//     addedSection: q("addedSection"),
//     deletedSection: q("deletedSection"),
//     modifiedSection: q("modifiedSection"),
//     addedList: q("addedList"),
//     deletedList: q("deletedList"),
//     modifiedList: q("modifiedList"),
//     addedTitleCount: q("addedTitleCount"),
//     deletedTitleCount: q("deletedTitleCount"),
//     modifiedTitleCount: q("modifiedTitleCount"),
//     searchBox: q("searchBox"),
//     themeToggle: q("themeToggle"),
//     reportTrigger: q("reportTrigger"),
//     reportDropdown: q("reportDropdown"),
//     reportSelectedText: q("reportSelectedText"),
//     reportCheckboxes: q("reportCheckboxes"),
//     compareReportsToggle: q("compareReportsToggle"),
//     searchFieldWrap: q("searchFieldWrap"),
//   };

//   /* ── Utils ───────────────────────────────────────────── */
//   function esc(s) {
//     var d = document.createElement("div");
//     d.textContent = s == null ? "" : String(s);
//     return d.innerHTML;
//   }

//   function animateCount(el, target) {
//     var start = 0;
//     var duration = 500;
//     var startTime = null;
//     function step(ts) {
//       if (!startTime) startTime = ts;
//       var progress = Math.min((ts - startTime) / duration, 1);
//       var ease = 1 - Math.pow(1 - progress, 3);
//       el.textContent = Math.round(ease * target);
//       if (progress < 1) requestAnimationFrame(step);
//     }
//     requestAnimationFrame(step);
//   }

//   function showToast(msg, type) {
//     var c = q("toastContainer");
//     var t = document.createElement("div");
//     t.className = "toast toast-" + (type || "info");
//     t.textContent = msg;
//     c.appendChild(t);
//     setTimeout(function () {
//       t.style.opacity = "0";
//       t.style.transform = "translateX(30px) scale(0.9)";
//       t.style.transition = "all .25s ease";
//       setTimeout(function () {
//         if (t.parentNode) t.parentNode.removeChild(t);
//       }, 280);
//     }, 3200);
//   }
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
        return (
          '<div class="' +
          cls +
          '">' +
          esc(line.replace(/\\\\n$/, "")) +
          "</div>"
        );
      })
      .join("");
  }
  function fieldRows(changes) {
    return Object.keys(changes || {})
      .map(function (k) {
        var v = changes[k];
        return (
          '<tr><td class="field-name">' +
          esc(k) +
          "</td>" +
          '<td class="val-old">' +
          esc(v.old) +
          "</td>" +
          '<td class="val-new">' +
          esc(v["new"]) +
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
      var rMeta = (thresholdData.reports || {})[basename];
      if (rMeta && rMeta.threshold_exceeded && rMeta.status === "pending") {
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
      els.metaGenerated.textContent = sr.generated_at || "—";
      els.metaPrev.textContent =
        sr.previous_snapshot || "(none — baseline run)";
      els.metaCurr.textContent = sr.current_snapshot || "—";
      els.subtitle.textContent = reports[indices[0]].label;
    } else {
      genAts.sort();
      els.metaGenerated.textContent =
        (genAts[0] || "?") + " → " + (genAts[genAts.length - 1] || "?");
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

    applySearchFilter();
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
        els.metaGenerated.textContent = targetEntry.data.generated_at || "-";
        els.metaPrev.textContent = baseId;
        els.metaCurr.textContent = targetId;
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

  /* ── Network Settings tab ────────────────────────────── */
  function fillNetTable(tableId, data) {
    var t = q(tableId);
    if (!t) return;
    var entries = Object.entries(data || {});
    if (!entries.length) {
      t.innerHTML =
        '<tr><td colspan="2" class="net-empty">No data collected</td></tr>';
      return;
    }
    t.innerHTML = entries
      .map(function (kv) {
        return (
          "<tr><td>" +
          esc(kv[0]) +
          "</td><td>" +
          esc(String(kv[1])) +
          "</td></tr>"
        );
      })
      .join("");
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
    fillNetTable("sysctlTable", networkData.sysctl_kernel);
    fillNetTable("cpuTable", networkData.cpu_isolation_power);
    fillNetTable("irqTable", networkData.irq_affinity);
    fillNetTable("nicTable", networkData.nic_ethtool);
    fillNetTable("timeTable", networkData.time_synchronization);
    fillNetTable("hpTable", networkData.hugepages_tuned);
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
            esc(r.snapshot_id) +
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
    var changeCount =
      (summary.added || 0) + (summary.deleted || 0) + (summary.modified || 0);
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
        } else {
          decisionPanel =
            '<section class="panel audit-panel">' +
            '<h2 class="panel-title"><span class="panel-dot dot-alert"></span>Pending Baseline Approval</h2>' +
            '<div class="audit-body">' +
            '<p class="audit-caption"><span class="audit-warn-count">' +
            changeCount +
            ' detected change(s)</span> in snapshot <span class="mono audit-snapshot-tag">' +
            esc(snapshot) +
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
        if (!decision) {
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
      if (ep || eg) {
        var exc = { include_content: ec };
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
          '<input type="text" class="exc-path" placeholder="Exact path" value="' +
          esc(e.path || "") +
          '">' +
          '<input type="text" class="exc-pattern" placeholder="Glob pattern" value="' +
          esc(e.pattern || "") +
          '">' +
          '<label class="toggle-label"><input type="checkbox" class="exc-content"' +
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
      '<input type="text" class="exc-path" placeholder="Exact path">' +
      '<input type="text" class="exc-pattern" placeholder="Glob pattern">' +
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

  fetchReportStatus();
  setInterval(fetchReportStatus, 30000);
})();
