/**
 * Mini-Colosseum Research Harness v2.0 Desktop Controller
 * Desktop proof workbench controller:
 * - Direct execution controls (Run All, Step, Pause, Stop, Re-explore)
 * - Dual-Model Routing: meta-models/muse-spark-open-1026 (Baseten) + muse-wonder-1.0 (Meta)
 * - Dual Credit Pool Monitors: $150 Meta API + $100 Baseten
 * - Structured analysis and review details
 * - Deterministic fingerprints and dynamic invalidation
 * - Exact-quote verification and review status
 * - Full trace export & offline replay import
 */

function escapeHTML(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

class MiniColosseumApp {
  constructor() {
    this.ws = null;
    this.currentRunId = null;
    this.currentRunData = {
      nodes: [],
      edges: [],
      events: [],
      assembled_latex: "",
      knowledge_directory: [],
      hmed_records: [],
    };
    this.selectedNode = null;
    this.activeTab = "doc";
    this.activeInspTab = "goals";
    this.filterSeverity = "all";
    this.filterSearchText = "";
    this.attachments = [];
    this.ledgerCostSort = false;
    this.sessionToken = (window.electronAPI && window.electronAPI.sessionToken) || null;

    this.initDOM();
    this.initRenderers();
    this.initSplitters();

    // Initialize session token, WebSocket, and startup key setup
    this.initSession();

    // Keep the spend display in step with the backend while a run is live.
    setInterval(() => { if (this.currentRunId) this.refreshBudgetFromServer(); }, 5000);
  }

  async initSession() {
    if (!this.sessionToken) {
      try {
        const res = await fetch("/session");
        if (res.ok) {
          const data = await res.json();
          this.sessionToken = data.token;
        }
      } catch (e) {
        console.warn("Could not fetch session token from /session:", e);
      }
    }

    // Install fetch auth interceptor so all requests send X-Session-Token (Section 5.2)
    this._installFetchAuthInterceptor();

    // Connect WebSocket
    this.connectWebSocket();

    // On software startup, ask user for API keys (FR8, Section 5.2, Section 9.5)
    this.checkFirstRunKeySetup();
  }

  _installFetchAuthInterceptor() {
    const origFetch = window.fetch;
    const self = this;
    window.fetch = function (input, init = {}) {
      init = init || {};
      const headers = new Headers(init.headers || {});
      if (self.sessionToken && !headers.has("X-Session-Token")) {
        headers.set("X-Session-Token", self.sessionToken);
      }
      init.headers = headers;
      return origFetch.call(window, input, init);
    };
  }

  initDOM() {
    document.getElementById("toolbar-problem-title")?.addEventListener("input", (event) => {
      const input = document.getElementById("input-problem");
      if (input) input.value = event.target.value;
      this.updateProblemTitle(event.target.value);
    });
    document.getElementById("input-problem")?.addEventListener("input", (event) => {
      this.updateProblemTitle(event.target.value);
    });
    // One problem statement only (maths or CS): the toolbar bar and the
    // modal textarea are two views of the same single statement.
    document.getElementById("input-attachments")?.addEventListener("change", (event) => {
      this.addAttachments(Array.from(event.target.files || []));
      event.target.value = "";
    });
    const dropZone = document.getElementById("attachment-drop-zone");
    if (dropZone) {
      ["dragenter", "dragover"].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => {
          event.preventDefault();
          dropZone.classList.add("drag-over");
        });
      });
      ["dragleave", "drop"].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => {
          event.preventDefault();
          dropZone.classList.remove("drag-over");
        });
      });
      dropZone.addEventListener("drop", (event) => {
        this.addAttachments(Array.from(event.dataTransfer.files || []));
      });
    }

    ["setup-input-api-key", "setup-input-baseten-key", "setup-input-fireworks-key"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", () => this.updateKeySaveState());
    });
    document.getElementById("setup-checkbox-baseten-fallback")?.addEventListener("change", () => this.updateKeySaveState());
    document.getElementById("setup-checkbox-fireworks-fallback")?.addEventListener("change", () => this.updateKeySaveState());
    document.querySelectorAll(".eye-toggle").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById(button.dataset.target);
        if (!input) return;
        input.type = input.type === "password" ? "text" : "password";
        button.textContent = input.type === "password" ? "Show" : "Hide";
      });
    });

    // Severity filter in console
    document.getElementById("log-filter-severity")?.addEventListener("change", (e) => {
      this.filterSeverity = e.target.value;
      this.filterEventLogs();
    });
    document.getElementById("log-search-input")?.addEventListener("input", () => {
      this.filterLogs();
    });
    document.getElementById("ledger-cost-header")?.addEventListener("click", () => this.sortLedgerByCost());
    document.getElementById("ledger-follow-latest")?.addEventListener("change", () => this.renderLedger());

    // The four rows in the Sections view open the matching inspector tab.
    const goalTargets = {
      "target-subgoal-1": "details",
      "target-subgoal-2": "details",
      "target-subgoal-3": "falsifier",
      "target-subgoal-4": "falsifier",
    };
    Object.entries(goalTargets).forEach(([id, tab]) => {
      document.getElementById(id)?.addEventListener("click", () => this.openInspectorSection(tab));
    });
    document.getElementById("menu-help-about")?.addEventListener("click", () => this.showAbout());

    // Editor container reference
    this.docContainer = document.getElementById("document-content");

    // Close dropdowns on clicking outside
    window.addEventListener("click", (e) => {
      if (!e.target.closest(".menu-item")) {
        document.querySelectorAll(".menu-item").forEach((m) => m.classList.remove("active"));
      }
    });

    // Menu dropdown toggles
    document.querySelectorAll(".menu-item").forEach((item) => {
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasActive = item.classList.contains("active");
        document.querySelectorAll(".menu-item").forEach((m) => m.classList.remove("active"));
        if (!wasActive) item.classList.add("active");
      });
    });

    // Replay state for Step / Back / Run to End (Section 5.3, FR5)
    this.replayEvents = [];        // Full event list for replay
    this.replayIndex = -1;         // Current position in replayEvents (-1 = not in replay)
    this.isReplayMode = false;     // True when viewing offline or stepped-back replay

    // Keyboard shortcuts (Section 8: F5, F6, Shift+F5, Ctrl+Right/Left/End, Ctrl+R)
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && document.getElementById("modal-first-run-setup")?.classList.contains("active")) {
        e.preventDefault();
        return;
      }
      if (e.key === "F5" && !e.shiftKey) {
        e.preventDefault();
        this.handleRunAll();
      } else if (e.key === "F5" && e.shiftKey) {
        e.preventDefault();
        this.handleStop();
      } else if (e.key === "F6") {
        e.preventDefault();
        this.handlePause();
      } else if (e.ctrlKey && e.key === "ArrowRight") {
        e.preventDefault();
        this.stepForward();
      } else if (e.ctrlKey && e.key === "ArrowDown") {
        e.preventDefault();
        this.stepForward();
      } else if (e.ctrlKey && e.key === "ArrowLeft") {
        e.preventDefault();
        this.stepBack();
      } else if (e.ctrlKey && e.key === "End") {
        e.preventDefault();
        this.runToEnd();
      } else if (e.ctrlKey && (e.key === "r" || e.key === "R")) {
        e.preventDefault();
        this.triggerReexplore();
      } else if (e.ctrlKey && e.key === "e") {
        e.preventDefault();
        this.triggerReexplore();
      } else if (e.ctrlKey && e.key === "n") {
        e.preventDefault();
        this.showModal("modal-run-setup");
      } else if (e.ctrlKey && e.key === "o") {
        e.preventDefault();
        this.openRunHistoryModal();
      }
    });
  }

  updateProblemTitle(statement) {
    const firstLine = String(statement || "").split(/\r?\n/, 1)[0].trim();
    const title = firstLine ? (firstLine.length > 80 ? `${firstLine.slice(0, 77)}...` : firstLine) : "Ready";
    const badge = document.getElementById("badge-problem");
    if (badge) badge.textContent = title;
    const toolbarInput = document.getElementById("toolbar-problem-title");
    if (toolbarInput && toolbarInput.value !== firstLine) toolbarInput.value = firstLine;
    const main = document.getElementById("status-main-label");
    if (main && !this.currentRunId) main.textContent = title;
    this.updatePreviewProblem();
  }

  updatePreviewProblem() {
    const preview = document.getElementById("preview-problem");
    if (!preview) return;
    const problem = (document.getElementById("input-problem")?.value || document.getElementById("toolbar-problem-title")?.value || "").trim();
    // Render LaTeX / superscripts / subscripts / symbols readably.
    preview.innerHTML = problem ? SimpleLaTeXRenderer.toReadable(problem) : "Enter a problem to begin.";
  }

  initRenderers() {
    const treeContainer = document.getElementById("tree-canvas-container");
    const dagContainer = document.getElementById("dag-canvas-container");

    this.treeRenderer = new GraphRenderer(treeContainer, (node) => this.selectNode(node));
    this.dagRenderer = new GraphRenderer(dagContainer, (node) => this.selectNode(node));
  }

  initSplitters() {
    const resizerX = document.getElementById("resizer-x");
    const leftPane = document.getElementById("left-pane");
    let isResizingX = false;

    resizerX.addEventListener("mousedown", () => {
      isResizingX = true;
      document.body.style.cursor = "col-resize";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizingX) return;
      const newWidth = Math.max(260, Math.min(e.clientX, window.innerWidth - 300));
      leftPane.style.width = `${newWidth}px`;
      leftPane.style.flex = "none";
    });

    window.addEventListener("mouseup", () => {
      if (isResizingX) {
        isResizingX = false;
        document.body.style.cursor = "default";
      }
    });

    const resizerPreview = document.getElementById("resizer-preview");
    const previewPane = document.getElementById("preview-pane");
    if (resizerPreview && previewPane) {
      let isResizingPreview = false;
      resizerPreview.addEventListener("mousedown", (e) => {
        isResizingPreview = true;
        document.body.style.cursor = "col-resize";
        e.preventDefault();
      });
      window.addEventListener("mousemove", (e) => {
        if (!isResizingPreview) return;
        const left = previewPane.getBoundingClientRect().left;
        const maxWidth = Math.max(200, window.innerWidth - left - 270);
        const newWidth = Math.max(180, Math.min(e.clientX - left, maxWidth));
        previewPane.style.width = `${newWidth}px`;
        previewPane.style.flex = "none";
      });
      window.addEventListener("mouseup", () => {
        if (isResizingPreview) {
          isResizingPreview = false;
          document.body.style.cursor = "default";
        }
      });
    }

    const resizerY = document.getElementById("resizer-y");
    const inspectorPane = document.getElementById("inspector-container");
    let isResizingY = false;

    resizerY.addEventListener("mousedown", () => {
      isResizingY = true;
      document.body.style.cursor = "row-resize";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizingY) return;
      const rightPaneRect = document.getElementById("right-pane").getBoundingClientRect();
      const newHeight = Math.max(100, Math.min(e.clientY - rightPaneRect.top, rightPaneRect.height - 80));
      inspectorPane.style.height = `${newHeight}px`;
    });

    window.addEventListener("mouseup", () => {
      if (isResizingY) {
        isResizingY = false;
        document.body.style.cursor = "default";
      }
    });
  }

  updateGutter(lineCount) {
    const gutter = document.getElementById("editor-gutter");
    if (!gutter) return;
    const totalLines = Math.max(1, Number(lineCount) || 0);
    let numbers = [];
    for (let i = 1; i <= totalLines; i++) {
      numbers.push(i);
    }
    gutter.innerHTML = numbers.join("<br>");
  }

  switchTab(tab) {
    this.activeTab = tab;
    ["tree", "dag", "doc"].forEach((t) => {
      const btn = document.getElementById(`tab-btn-${t}`);
      const content = document.getElementById(`tab-${t}`);
      if (t === tab) {
        btn?.classList.add("active");
        content?.classList.add("active");
      } else {
        btn?.classList.remove("active");
        content?.classList.remove("active");
      }
    });

    if (tab === "tree") {
      requestAnimationFrame(() => this.treeRenderer?.fitToScreen());
      setTimeout(() => this.treeRenderer?.fitToScreen(), 50);
      setTimeout(() => this.treeRenderer?.fitToScreen(), 180);
    }
    if (tab === "dag") {
      requestAnimationFrame(() => this.dagRenderer?.fitToScreen());
      setTimeout(() => this.dagRenderer?.fitToScreen(), 50);
      setTimeout(() => this.dagRenderer?.fitToScreen(), 180);
    }
    if (tab === "doc") this.renderDocument();
  }

  // Clicking a row in the Sections view jumps to the tab that explains it.
  openInspectorSection(tab) {
    this.switchInspectorTab(tab);
    const pane = document.getElementById("coq-goals-container");
    if (pane) pane.scrollTop = 0;
    if (this.selectedNode) this.highlightDocumentSection(this.selectedNode);
  }

  showAbout() {
    alert("Mini-Colosseum v2.0\n\nEnter a problem, run it, and follow each step of the work on the right. Previous runs are kept under File > Previous Runs so you can view them again without running anything new.");
  }

  switchInspectorTab(tab) {
    this.activeInspTab = tab;
    ["goals", "details", "falsifier", "verifier", "hmed", "knowledge"].forEach((t) => {
      const tabEl = document.getElementById(`tab-insp-${t}`);
      const viewEl = document.getElementById(`view-insp-${t}`);
      if (t === tab) {
        tabEl?.classList.add("active");
        if (viewEl) viewEl.style.display = "block";
      } else {
        tabEl?.classList.remove("active");
        if (viewEl) viewEl.style.display = "none";
      }
    });

    if (tab === "knowledge") {
      this.renderKnowledgeTab();
    }
  }

  renderKnowledgeTab() {
    const kEl = document.getElementById("insp-knowledge-content");
    if (!kEl) return;
    const entries = this.currentRunData.knowledge_directory || [];
    if (!entries || entries.length === 0) {
      kEl.textContent = "Nothing here yet. Notes from your runs will appear here as they are made; nothing is added in advance.";
      return;
    }
    let text = `=== REFERENCE NOTES (${entries.length} entries from this run) ===\n\n`;
    entries.forEach((e, idx) => {
      const type = (e.entry_type || "claim").toUpperCase();
      const status = e.status || "unverified";
      text += `[${idx + 1}] [${type}] ${status.toUpperCase()} - ${e.title || ""}\n`;
      if (e.contents) text += `    ${e.contents}\n`;
      if (e.source) text += `    Source: ${e.source}\n`;
      text += "\n";
    });
    kEl.textContent = text;
  }

  jumpToSubgoal(subgoalIdx) {
    const node = this.currentRunData.nodes.find((n) => n.id === `SEC_${subgoalIdx}`);
    if (node) {
      this.selectNode(node);
      this.switchTab("dag");
    }
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "localhost:8765";
    const tokenParam = this.sessionToken ? `?token=${encodeURIComponent(this.sessionToken)}` : "";
    const wsUrl = `${protocol}//${host}/ws${tokenParam}`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onmessage = (event) => {
        try {
          const ev = JSON.parse(event.data);
          this.handleLiveEvent(ev);
        } catch (e) {
          console.error("WS Parse error:", e);
        }
      };

      this.ws.onclose = () => {
        setTimeout(() => this.connectWebSocket(), 3000);
      };
    } catch (e) {
      console.warn("WebSocket could not connect. Running offline simulation mode.");
    }
  }

  handleLiveEvent(ev) {
    this.currentRunData.events.push(ev);

    switch (ev.event_type) {
      case "round_started":
        document.getElementById("status-stage-label").textContent = `Round ${ev.payload.round}`;
        break;

      case "stage_changed":
        document.getElementById("status-stage-label").textContent = `Stage: ${ev.payload.stage.toUpperCase()}`;
        if (ev.payload.stage === "solving") {
          this.switchTab("dag");
        } else if (ev.payload.stage === "verification") {
          this.renderDocument();
        }
        break;

      case "node_created":
        const newNode = ev.payload.node;
        const exists = this.currentRunData.nodes.find((n) => n.id === newNode.id);
        if (!exists) this.currentRunData.nodes.push(newNode);
        this.updateGraphs();
        break;

      case "node_updated":
        const updatedNode = ev.payload.node;
        const idx = this.currentRunData.nodes.findIndex((n) => n.id === updatedNode.id);
        if (idx !== -1) {
          this.currentRunData.nodes[idx] = updatedNode;
        } else {
          this.currentRunData.nodes.push(updatedNode);
        }
        this.updateGraphs();
        if (this.selectedNode && this.selectedNode.id === updatedNode.id) {
          this.selectNode(updatedNode);
        }
        this.renderDocument();
        break;

      case "edge_added":
        const newEdge = ev.payload.edge;
        const edgeExists = this.currentRunData.edges.some(
          (e) => e.source === newEdge.source && e.target === newEdge.target
        );
        if (!edgeExists) this.currentRunData.edges.push(newEdge);
        this.updateGraphs();
        break;

      case "knowledge_entry_added":
        if (ev.payload && ev.payload.entry) {
          this.currentRunData.knowledge_directory.push(ev.payload.entry);
          if (this.activeInspTab === "knowledge") {
            this.renderKnowledgeTab();
          }
        }
        break;

      case "log_line":
        this.appendLogEntry(ev.timestamp, ev.payload.stage, ev.payload.severity, ev.payload.text, ev.payload.node_id);
        break;

      case "provider_fallback":
        this.appendLogEntry(ev.timestamp, "all", "warning", `Provider fallback: ${ev.payload.from_provider}/${ev.payload.from_model} -> ${ev.payload.to_provider}/${ev.payload.to_model} (${ev.payload.reason || "provider failure"})`);
        break;

      case "error":
        this.appendLogEntry(ev.timestamp, "all", "error", `Run error: ${ev.payload.error || "unknown error"}`);
        document.getElementById("status-stage-label").textContent = "Stage: FAILED";
        break;

      case "budget_warning":
        this.appendLogEntry(ev.timestamp, "all", "error", `BUDGET CAP REACHED: ${ev.payload.message}`);
        alert(`BUDGET WARNING: ${ev.payload.message}`);
        break;

      case "run_finished":
        this.currentRunData.assembled_latex = ev.payload.assembled_latex || this.currentRunData.assembled_latex;
        this.renderDocument();
        this.appendLogEntry(ev.timestamp, "all", "info", `Run finished. Status: ${ev.payload.status}. Assembled proof complete.`);
        document.getElementById("status-stage-label").textContent =
          ev.payload.status === "completed" ? "Stage: PROVED [Qed]" : `Stage: ${(ev.payload.status || "finished").toUpperCase()}`;
        this.updatePreviewProof();
        this.refreshBudgetFromServer(true);
        break;
    }

    this.updateStatusMetrics();
  }

  updateGraphs() {
    const treeNodes = this.currentRunData.nodes.filter(
      (n) => n.stage === "exploration" || n.type === "explorer" || n.type === "aggregator" || n.type === "gate"
    );
    const treeEdges = this.currentRunData.edges.filter((e) => e.edge_type === "aggregation" || e.type === "aggregation");
    this.treeRenderer.setData(treeNodes, treeEdges, { collapsePriorRounds: true });

    const dagNodes = this.currentRunData.nodes.filter(
      (n) => n.stage === "solving" || n.type === "solver" || n.type === "decomposer"
    );
    const dagEdges = this.currentRunData.edges.filter((e) => e.edge_type === "dependency" || e.type === "dependency");
    this.dagRenderer.setData(dagNodes, dagEdges);
  }

  updateStatusMetrics() {
    let totalCost = 0;
    let metaCost = 0;
    let basetenCost = 0;
    let totalIn = 0;
    let totalCached = 0;
    let totalOut = 0;
    let calls = this.currentRunData.nodes.length;

    this.currentRunData.nodes.forEach((n) => {
      const c = n.cost_usd || 0;
      totalCost += c;
      const p = n.provider || "meta";
      if (p === "meta") {
        metaCost += c;
      } else {
        basetenCost += c;
      }
      totalIn += n.tokens_in || 0;
      totalCached += n.tokens_cached || 0;
      totalOut += n.tokens_out || 0;
    });

    const sc = document.getElementById("status-calls");
    if (sc) sc.textContent = `Calls: ${calls}`;
    const totalTokK = Math.round((totalIn + totalOut) / 1000);
    const cachedTokK = Math.round(totalCached / 1000);
    const st = document.getElementById("status-tokens");
    if (st) st.textContent = `${totalTokK}k tok (${cachedTokK}k cached)`;

    const smb = document.getElementById("status-meta-budget");
    if (smb) smb.textContent = `Meta: $${metaCost.toFixed(3)} / $150`;

    const sbb = document.getElementById("status-baseten-budget");
    if (sbb) sbb.textContent = `Baseten: $${basetenCost.toFixed(3)} / $100`;

    // Authoritative spend comes from the backend's per-provider accounting
    // (node costs mix providers, e.g. a falsifier's Meta cost sits on a
    // Spark node, so summing nodes misattributes spend). Throttled poll.
    this.refreshBudgetFromServer();

    const hardCap = parseFloat(document.getElementById("input-run-budget-cap")?.value || "50");
    const sco = document.getElementById("status-cost");
    if (sco) sco.textContent = `SPEND: $${totalCost.toFixed(3)} / $${hardCap.toFixed(2)}`;
    const referenceSpend = document.getElementById("reference-spend");
    if (referenceSpend) referenceSpend.textContent = `SPEND: $${totalCost.toFixed(2)} / $${hardCap.toFixed(2)}`;
    this.renderLedger();
  }

  refreshBudgetFromServer(force = false) {
    const now = Date.now();
    if (!force && this._budgetFetchAt && now - this._budgetFetchAt < 2000) return;
    this._budgetFetchAt = now;
    fetch("/api/budget/pools")
      .then((r) => (r.ok ? r.json() : null))
      .then((pools) => {
        if (!pools) return;
        const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
        set("status-meta-budget", `Meta: $${pools.meta_usage.toFixed(3)} / $${pools.meta_budget.toFixed(0)}`);
        set("status-baseten-budget", `Baseten: $${pools.baseten_usage.toFixed(3)} / $${pools.baseten_budget.toFixed(0)}`);
        set("fireworks-status", `Fireworks: $${pools.fireworks_usage.toFixed(3)} / $${pools.fireworks_budget.toFixed(0)}`);
        set("status-calls", `Calls: ${pools.calls}`);
        const tokK = Math.round(((pools.tokens_in || 0) + (pools.tokens_out || 0)) / 1000);
        const cachedK = Math.round((pools.tokens_cached || 0) / 1000);
        set("status-tokens", `${tokK}k tok (${cachedK}k cached)`);
        const hardCap = parseFloat(document.getElementById("input-run-budget-cap")?.value || "50");
        set("status-cost", `SPEND: $${pools.total_usage.toFixed(3)} / $${hardCap.toFixed(2)}`);
        set("reference-spend", `SPEND: $${pools.total_usage.toFixed(2)} / $${hardCap.toFixed(2)}`);
      })
      .catch(() => { /* keep node-based estimate */ });
  }

  openLedger() {
    this.renderLedger();
    this.showModal("modal-ledger");
  }

  sortLedgerByCost() {
    this.ledgerCostSort = !this.ledgerCostSort;
    this.renderLedger();
  }

  renderLedger() {
    const body = document.getElementById("ledger-body");
    const summary = document.getElementById("ledger-summary");
    if (!body || !summary) return;
    const rows = this.currentRunData.nodes.map((node, index) => ({ node, index }));
    if (this.ledgerCostSort) rows.sort((a, b) => (b.node.cost_usd || 0) - (a.node.cost_usd || 0));
    const total = rows.reduce((sum, item) => sum + (item.node.cost_usd || 0), 0);
    const top = [...rows].sort((a, b) => (b.node.cost_usd || 0) - (a.node.cost_usd || 0)).slice(0, 3);
    const topIds = new Set(top.map((item) => item.node.id));
    const stageTotals = {};
    this.currentRunData.nodes.forEach((node) => {
      stageTotals[node.stage || "unknown"] = (stageTotals[node.stage || "unknown"] || 0) + (node.cost_usd || 0);
    });
    const topStage = Object.entries(stageTotals).sort((a, b) => b[1] - a[1])[0];
    summary.textContent = `Total $${total.toFixed(3)} | Calls ${rows.length} | Most expensive ${top[0]?.node.label || top[0]?.node.type || "—"} ($${(top[0]?.node.cost_usd || 0).toFixed(3)}) | Stage ${topStage ? `${topStage[0]} ($${topStage[1].toFixed(3)})` : "—"}`;
    body.innerHTML = "";
    rows.forEach(({ node, index }) => {
      const cost = node.cost_usd || 0;
      const share = total ? (cost / total) * 100 : 0;
      const row = document.createElement("tr");
      row.title = node.id || "";
      row.innerHTML = `<td>${index + 1}</td><td>${escapeHTML(node.stage || "—")}</td><td>${escapeHTML(this.plainNodeName(node))} ${topIds.has(node.id) ? '<span class="top-cost-badge">Top cost</span>' : ""}</td><td>${escapeHTML(node.model || "—")}</td><td class="cost-cell">$${cost.toFixed(3)}</td><td><span class="share-bar"><span style="width:${share}%"></span></span>${share.toFixed(1)}%</td>`;
      row.addEventListener("click", () => this.selectNode(node));
      body.appendChild(row);
    });
    if (document.getElementById("ledger-follow-latest")?.checked) {
      const wrap = document.querySelector("#modal-ledger .ledger-table-wrap");
      if (wrap) wrap.scrollTop = wrap.scrollHeight;
    }
  }

  plainNodeName(node) {
    if (node.label) return node.label;
    const section = node.output?.section_index || node.section_index;
    if (node.type === "solver" && section) return `Section ${section}, Writer ${node.round || 1}`;
    if (node.type === "falsifier" || node.type === "section_falsifier") {
      return `Review of Candidate ${node.round || 1}`;
    }
    return node.type || "Node";
  }

  exportSelected(type) {
    if (!type) return;
    if (!this.currentRunId) {
      alert("No saved run is selected.");
      return;
    }
    const tokenQuery = this.sessionToken ? `?token=${encodeURIComponent(this.sessionToken)}` : "";
    window.open(`/api/runs/${this.currentRunId}/export/${type}${tokenQuery}`, "_blank");
    const select = document.getElementById("export-select");
    if (select) select.value = "";
  }

  selectNode(node) {
    if (!node) return;
    this.selectedNode = node;
    this.treeRenderer.setSelectedNode(node.id);
    this.dagRenderer.setSelectedNode(node.id);

    const subgoalsCountEl = document.getElementById("coq-subgoals-count");
    const hypothesesEl = document.getElementById("coq-hypotheses-text");
    const tag1El = document.getElementById("tag-subgoal-1");
    const target1El = document.getElementById("target-subgoal-1");
    const tag2El = document.getElementById("tag-subgoal-2");
    const target2El = document.getElementById("target-subgoal-2");
    const tag3El = document.getElementById("tag-subgoal-3");
    const target3El = document.getElementById("target-subgoal-3");
    const tag4El = document.getElementById("tag-subgoal-4");
    const target4El = document.getElementById("target-subgoal-4");

    const statusStyle = this.treeRenderer.getStatusStyle(node.status);
    const label = node.label || node.id;
    const out = node.output || {};

    let hypotheses = `Selected section : ${label}\nStatus          : ${node.status || "Ready"}\nProgress        : ${statusStyle.glyph}`;
    if (hypothesesEl) hypothesesEl.textContent = hypotheses;

    // 2. Format 4 Authentic Subgoals
    if (subgoalsCountEl) subgoalsCountEl.textContent = `Selected: ${label} (${node.type || "node"}, ${node.status || "pending"})`;

    const targetObligation = node.input_summary || out.target_claim || "Review the selected problem target.";
    if (tag1El) tag1El.textContent = "(1/4) Problem target";
    if (target1El) target1El.textContent = targetObligation;

    let planSummary = out.primary_route || out.claimed_result || "Proposed approach.";
    if (node.analysis && node.analysis.plan) {
      planSummary = node.analysis.plan;
      if (node.analysis.uncertainties && node.analysis.uncertainties.length > 0) {
        planSummary += `\nOpen questions: ${node.analysis.uncertainties.join("; ")}`;
      }
    }
    if (tag2El) tag2El.textContent = "(2/4) Proposed approach";
    if (target2El) target2El.textContent = planSummary;

    let falsifierSummary = "No review is available for this section.";
    if (node.falsifier_report) {
      const f = node.falsifier_report;
      falsifierSummary = `${f.verdict || "Review"}: ${f.assessment || ""}`;
      if (f.weakest_lemmas && f.weakest_lemmas.length > 0) {
        falsifierSummary += `\nItems to revisit: ${f.weakest_lemmas.join(", ")}`;
      }
    }
    if (tag3El) tag3El.textContent = "(3/4) Review result";
    if (target3El) target3El.textContent = falsifierSummary;

    let objectionsSummary = "No open issues.";
    const objs = (node.falsifier_report && node.falsifier_report.categorized_objections) || node.objections || [];
    if (objs.length > 0) {
      objectionsSummary = objs.map((o) => `${(o.severity || "Issue").toUpperCase()}: ${o.claim || o}`).join("\n");
    } else if (out.preserved_critiques && out.preserved_critiques.length > 0) {
      objectionsSummary = `${out.preserved_critiques.length} items carried forward for review.`;
    }
    if (tag4El) tag4El.textContent = "(4/4) Open issues";
    if (target4El) target4El.textContent = objectionsSummary;

    // 3. Populate the selected section details.
    const metaEl = document.getElementById("insp-meta-text");
    if (metaEl) {
      const primaryProv = node.primary_provider || "meta";
      const primaryMod = node.primary_model || (node.model && node.model.includes("wonder") ? "muse-wonder-1.0" : "muse-spark-1.3");
      const actualProv = (node.provider || "meta").toUpperCase();
      const actualMod = node.model || "muse-spark-1.3";
      const fallbackBadge = node.fallback_used
        ? `<span style="color:#b25900; font-weight:bold;">Fallback Used</span> (${escapeHTML(node.fallback_reason || "Eligible failover")})`
        : `<span style="color:#007700;">Standard Primary</span>`;

      metaEl.innerHTML = `
        <strong>Node:</strong> ${escapeHTML(label)} (${escapeHTML(node.id)}) | <strong>Stage:</strong> ${escapeHTML(node.stage)} (Round ${node.round || 1})<br>
        <strong>Primary:</strong> ${escapeHTML(primaryProv.toUpperCase())} / ${escapeHTML(primaryMod)} | <strong>Actual:</strong> ${escapeHTML(actualProv)} / ${escapeHTML(actualMod)}<br>
        <strong>Status:</strong> ${fallbackBadge} | <strong>Cost:</strong> $${(node.cost_usd || 0).toFixed(6)}<br>
        <strong>Tokens:</strong> In ${node.tokens_in || 0} (${node.tokens_cached || 0} cached) | Out ${node.tokens_out || 0}
      `;
    }

    const analysisEl = document.getElementById("insp-analysis-content");
    if (analysisEl) {
      const a = node.analysis || (out && out.analysis);
      if (a) {
        let uncList = (a.uncertainties || []).map((u) => `• ${escapeHTML(u)}`).join("<br>");
        analysisEl.innerHTML = `
          <div style="margin-bottom:4px;"><strong>Available Info:</strong> ${escapeHTML(a.available_info || "None specified")}</div>
          <div style="margin-bottom:4px;"><strong>Plan:</strong> ${escapeHTML(a.plan || "None specified")}</div>
          <div><strong>Uncertainties:</strong><br>${uncList || "None"}</div>
        `;
      } else {
        analysisEl.innerHTML = `<em>No additional details are available for this section.</em>`;
      }
    }

    const inEl = document.getElementById("insp-input-content");
    if (inEl) inEl.textContent = node.input_summary || "Prompt summary.";

    const outEl = document.getElementById("insp-output-content");
    if (outEl) {
      // Show the node's actual math first (claim + proof body), then raw JSON.
      const bodyText = out.solution_body || out.latex_body || out.proof_body || out.proof || out.body || "";
      const claimText = out.claimed_result || out.target_claim || "";
      let outText = "";
      if (claimText) outText += `Claim: ${claimText}\n\n`;
      if (bodyText) outText += `${bodyText}\n\n--- Full output (JSON) ---\n`;
      outText += JSON.stringify(out, null, 2);
      if (node.rollouts && node.rollouts.length > 0) {
        outText = `// Test-Time Scaling: ${node.rollouts.length} Parallel Rollouts\n` + outText;
      }
      outEl.textContent = outText;
    }

    const fEl = document.getElementById("insp-falsifier-content");
    if (fEl) {
      if (node.falsifier_report) {
        const f = node.falsifier_report;
        let fText = `Verdict: ${f.verdict}\nAssessment: ${f.assessment || ""}\n`;
        if (f.weakest_lemmas && f.weakest_lemmas.length) {
          fText += `\nWeakest Lemmas: ${f.weakest_lemmas.join(", ")}\n`;
        }
        if (f.categorized_objections && f.categorized_objections.length) {
          fText += `\nCategorized Objections:\n${JSON.stringify(f.categorized_objections, null, 2)}\n`;
        }
        if (out.preserved_critiques && out.preserved_critiques.length) {
          fText += `\nPreserved Parent Critiques:\n${JSON.stringify(out.preserved_critiques, null, 2)}\n`;
        }
        if (node.rollouts && node.rollouts.length > 0) {
          fText += `\nWriter drafts and their attached critiques (${node.rollouts.length}):\n`;
          node.rollouts.forEach((draft, di) => {
            const crit = draft.falsifier_critique || {};
            fText += `\n--- Draft ${di + 1} ---\nCritique verdict: ${crit.verdict || "not recorded"}\n`;
            if (crit.assessment) fText += `Assessment: ${crit.assessment}\n`;
            (crit.objections || []).forEach((o) => {
              fText += `- [${o.severity || "major"}] ${o.claim_attacked || o.claim || ""}: ${o.why || ""}\n`;
            });
          });
        }
        fEl.textContent = fText;
      } else {
        if (node.rollouts && node.rollouts.length > 0) {
          let fText = `Writer drafts and their attached critiques (${node.rollouts.length}):\n`;
          node.rollouts.forEach((draft, di) => {
            const crit = draft.falsifier_critique || {};
            fText += `\n--- Draft ${di + 1} ---\nCritique verdict: ${crit.verdict || "not recorded"}\n`;
            if (crit.assessment) fText += `Assessment: ${crit.assessment}\n`;
            (crit.objections || []).forEach((o) => {
              fText += `- [${o.severity || "major"}] ${o.claim_attacked || o.claim || ""}: ${o.why || ""}\n`;
            });
          });
          fEl.textContent = fText;
        } else {
          fEl.textContent = "No review is available for this section.";
        }
      }
    }

    const verifEl = document.getElementById("insp-verifier-content");
    if (verifEl) {
      const verifNode = this.currentRunData.nodes.find((n) => n.type === "global_verifier");
      if (verifNode && verifNode.output) {
        const v = verifNode.output;
        let vHtml = `<div style="font-weight:bold; margin-bottom:6px; color:#005500;">Verdict: ${(v.verdict || "unknown").toUpperCase()}${v.exact_quotes_checked !== undefined ? ` (Exact quotes passed: ${v.exact_quotes_passed || 0}/${v.exact_quotes_checked})` : ""}</div>`;
        vHtml += `<div style="margin-bottom:8px;">${v.summary || ""}</div>`;

        const defects = v.defects || [];
        if (defects.length === 0) {
          vHtml += `<div style="color:#007700; font-weight:bold;">[Q.E.D.] 0 Fatal Defects Detected in Assembled LaTeX.</div>`;
        } else {
          vHtml += `<div style="font-weight:bold; margin-bottom:4px;">Issue review:</div>`;
          defects.forEach((d, idx) => {
            const isVerified = d.quote_verified;
            const isDowngraded = d.downgraded_warning;
            const badgeClass = isVerified ? "color:#007700;" : (isDowngraded ? "color:#cc6600;" : "color:#cc0000;");
            const badgeLabel = isVerified ? "[OK: Quote Verified]" : (isDowngraded ? "[!] Downgraded Warning: Unmatched Quote" : "[Fatal Defect]");

            vHtml += `
              <div style="border:1px solid #c8c6bc; background:#ffffff; padding:6px; margin-bottom:6px;">
                <span style="${badgeClass} font-weight:bold;">${badgeLabel}</span> (Section: ${escapeHTML(String(d.section_index ?? d.section_id ?? d.section ?? "Global"))})<br>
                <strong>Description:</strong> ${escapeHTML(d.description || d.claim || "")}<br>
                <strong>Exact Quote:</strong> <code>"${escapeHTML(d.exact_quote || "N/A")}"</code><br>
                ${(d.suggested_action || d.suggested_repair) ? `<strong>Suggested Repair:</strong> ${escapeHTML(d.suggested_action || d.suggested_repair)}` : ""}
              </div>
            `;
          });
        }
        verifEl.innerHTML = vHtml;
      } else {
        verifEl.innerHTML = `<em>Verification will appear after the proof is assembled.</em>`;
      }
    }

    const hmedEl = document.getElementById("insp-hmed-content");
    if (hmedEl) {
      let hHtml = "";
      if (node.danus_fingerprint) {
        hHtml += `
          <div style="border:1px solid #2b579a; background:#e8f0fe; padding:6px; margin-bottom:8px;">
            <strong style="color:#1b3a6b;">Section identity:</strong><br>
            Reference: <code>${node.danus_fingerprint}</code><br>
            Status: <strong>${node.is_invalidated ? "Needs refresh" : (node.is_stale ? "Update pending" : "Current")}</strong>
          </div>
        `;
      }

      const hmedRecords = this.currentRunData.hmed_records || [];
      const secIdx = out.section_index || parseInt(String(node.id || "").replace(/\D+/g, ""), 10) || 0;
      const nodeHmed = hmedRecords.filter((r) => r.subproblem_index === secIdx);
      if (nodeHmed.length > 0) {
        hHtml += `<strong>Revision records (${nodeHmed.length}):</strong><br>`;
        nodeHmed.forEach((rec, idx) => {
          hHtml += `
            <div style="border:1px solid #c8c6bc; background:#f4f3ec; padding:6px; margin-top:6px; font-size:10.5px;">
              <strong>Revision ${idx + 1} (Subproblem ${escapeHTML(String(rec.subproblem_index || ""))}):</strong><br>
              <strong>Critique:</strong> ${escapeHTML(rec.critique || "")}<br>
              <strong>Failed draft:</strong> ${escapeHTML(String(rec.failed_draft || "").substring(0, 400))}<br>
              <strong>Revised draft:</strong> ${escapeHTML(String(rec.revised_draft || "").substring(0, 400))}<br>
              <strong>Downstream verdict:</strong> ${escapeHTML(rec.downstream_verdict || "")}<br>
              <strong>Cost:</strong> $${(rec.cost_usd || 0).toFixed(4)} (solver ${escapeHTML(rec.model_solver || "")} / reviewer ${escapeHTML(rec.model_falsifier || "")})
            </div>
          `;
        });
      } else {
        hHtml += `<em>No revision records for this section.</em>`;
      }
      hmedEl.innerHTML = hHtml;
    }

    const sml = document.getElementById("status-main-label");
    if (sml) sml.textContent = `Ready in Predicate_Logic, proving ${label}`;
  }

  highlightDocumentSection(node) {
    if (node.stage === "solving" || node.type === "solver") {
      const secIdx = parseInt(node.id.replace("SEC_", ""), 10);
      const secEl = document.querySelector(`.document-section[data-section-idx="${secIdx}"]`);
      if (secEl) {
        secEl.scrollIntoView({ behavior: "smooth", block: "center" });
        secEl.style.outline = "2px solid #0000cc";
        setTimeout(() => (secEl.style.outline = "none"), 2000);
      }
    }
  }

  renderDocument() {
    const secNodes = this.currentRunData.nodes.filter((n) => n.type === "solver" || n.stage === "solving");
    const verifNode = this.currentRunData.nodes.find((n) => n.type === "global_verifier");
    const defects = verifNode && verifNode.output ? verifNode.output.defects || [] : [];

    // If the run stopped before a proof was assembled, show what did
    // happen (the strategies tried and where it stopped) instead of a blank.
    let latexForRender = this.currentRunData.assembled_latex;
    if (!latexForRender && secNodes.length === 0 && this.currentRunData.nodes.length > 0) {
      const parts = [];
      this.currentRunData.nodes.forEach((n) => {
        const out = n.output || {};
        let main = out.primary_route || out.assessment || out.explanation || out.rationale || "";
        if (main && typeof main !== "string") main = main.raw || JSON.stringify(main);
        const claim = out.normalized_problem || out.target_claim || "";
        if (main || claim) {
          parts.push(`\\section{${n.label || n.type} (${n.status || ""})}`);
          if (claim) parts.push(claim);
          if (main) parts.push(String(main));
        }
      });
      latexForRender = parts.join("\n");
    }

    const rendered = SimpleLaTeXRenderer.renderDocument(
      latexForRender,
      secNodes,
      defects
    );
    if (this.docContainer) {
      this.docContainer.innerHTML = rendered;
      const lineCount = rendered.split("<div class=\"coq-line").length;
      this.updateGutter(lineCount);
    }
    this.updatePreviewProof();
  }

  updatePreviewProof() {
    const container = document.getElementById("live-preview-content");
    if (!container) return;
    let proofEl = document.getElementById("preview-proof");
    if (!proofEl) {
      proofEl = document.createElement("div");
      proofEl.id = "preview-proof";
      proofEl.className = "preview-proof";
      container.appendChild(proofEl);
    }
    const latex = (this.currentRunData.assembled_latex || "").trim();
    if (latex) {
      const secNodes = this.currentRunData.nodes.filter((n) => n.type === "solver" || n.stage === "solving");
      proofEl.innerHTML = SimpleLaTeXRenderer.renderDocument(latex, secNodes, []);
    } else {
      proofEl.textContent = "Proof text will appear here as sections are solved.";
    }
  }

  appendLogEntry(timestamp, stage, severity, text, nodeId = null) {
    const stream = document.getElementById("event-log-stream");
    if (!stream) return;
    const entry = document.createElement("div");
    entry.className = `coq-msg-line ${severity}`;
    entry.setAttribute("data-stage", stage);
    entry.setAttribute("data-severity", severity);
    if (nodeId) entry.setAttribute("data-node-id", nodeId);

    const timeSpan = document.createElement("span");
    timeSpan.style.color = "#666660";
    timeSpan.textContent = `[${timestamp}] `;

    const stageStrong = document.createElement("strong");
    stageStrong.textContent = `[${stage.toUpperCase()}] `;

    const textNode = document.createTextNode(text);

    entry.appendChild(timeSpan);
    entry.appendChild(stageStrong);
    entry.appendChild(textNode);

    if (nodeId) {
      entry.addEventListener("click", () => {
        const n = this.currentRunData.nodes.find((x) => x.id === nodeId);
        if (n) this.selectNode(n);
      });
    }

    stream.appendChild(entry);
    stream.scrollTop = stream.scrollHeight;
  }

  filterLogs() {
    const query = document.getElementById("log-search-input")?.value || "";
    this.filterSearchText = query.trim().toLowerCase();
    this.filterEventLogs();
  }

  filterEventLogs() {
    const entries = document.querySelectorAll(".coq-msg-line");
    entries.forEach((el) => {
      const sev = el.getAttribute("data-severity");
      const matchSev = this.filterSeverity === "all" || sev === this.filterSeverity;
      const text = el.textContent.toLowerCase();
      const matchSearch = !this.filterSearchText || text.includes(this.filterSearchText);
      el.style.display = (matchSev && matchSearch) ? "block" : "none";
    });
  }

  async handleRunAll() {
    const statement = document.getElementById("input-problem")?.value || document.getElementById("toolbar-problem-title")?.value || "";
    this.updatePreviewProblem();
    const hardCap = parseFloat(document.getElementById("input-run-budget-cap")?.value || "50");
    if (!statement.trim() && this.attachments.length === 0) {
      alert("Enter a problem statement or attach a document.");
      this.showModal("modal-run-setup");
      return;
    }
    if (!Number.isFinite(hardCap) || hardCap < 0.5) {
      alert("Budget cap must be at least $0.50 in $0.50 increments.");
      this.showModal("modal-run-setup");
      return;
    }

    // Reset current run UI
    this.currentRunData = { nodes: [], edges: [], events: [], assembled_latex: "", knowledge_directory: [], hmed_records: [] };
    document.getElementById("event-log-stream").innerHTML = "";
    document.getElementById("status-stage-label").textContent = "Stage: EXPLORING";

    this.setCommandBusy("Starting run", true);
    document.getElementById("status-stage-label").textContent = "Stage: STARTING…";
    this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "info", `Starting Mini-Colosseum v2.0 pipeline on: ${statement.substring(0, 60)}...`);

    try {
      const attachments = await Promise.all(this.attachments.map(async (file) => ({
        name: file.name,
        size: file.size,
        content_base64: this.arrayBufferToBase64(await file.arrayBuffer()),
      })));
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      let res;
      try {
        res = await fetch("/api/runs/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            problem_statement: statement,
            budget_cap_usd: hardCap,
            max_rounds: Math.max(1, Math.min(20, parseInt(document.getElementById("input-max-rounds")?.value || "15", 10) || 15)),
            tree_widths: (document.getElementById("input-tree-widths")?.value || "12, 8, 4, 1")
              .split(",")
              .map((s) => parseInt(s.trim(), 10))
              .filter((n) => Number.isFinite(n) && n > 0),
            k_sample: Math.max(2, Math.min(8, parseInt(document.getElementById("input-k-sample")?.value || "4", 10) || 4)),
            k_rollouts: Math.max(2, Math.min(8, parseInt(document.getElementById("input-k-sample")?.value || "4", 10) || 4)),
            cross_model_review: true,
            attachments,
          }),
        });
      } finally {
        clearTimeout(timer);
      }
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Unable to start run");
      }
      this.currentRunId = data.run_id;
      this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "info", `Run started (id ${data.run_id}). Waiting for the first model response…`);
      this.refreshBudgetFromServer();
    } catch (e) {
      const msg = e.name === "AbortError"
        ? "Starting the run timed out after 20s with no reply. The run may not have started; check the messages below."
        : `Failed to start run: ${e.message || e}`;
      this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "error", msg);
      document.getElementById("status-stage-label").textContent = "Stage: START FAILED";
      alert(msg);
    } finally {
      this.setCommandBusy("Starting run", false);
    }
  }

    arrayBufferToBase64(buffer) {
      let binary = "";
      const bytes = new Uint8Array(buffer);
      for (let index = 0; index < bytes.length; index += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
      }
      return btoa(binary);
    }

    addAttachments(files) {
      const allowed = new Set(["pdf", "doc", "docx", "tex"]);
      for (const file of files) {
        const extension = file.name.toLowerCase().split(".").pop();
        if (!allowed.has(extension)) {
          alert(`${file.name}: unsupported file type.`);
          continue;
        }
        if (file.size > 20 * 1024 * 1024) {
          alert(`${file.name}: files must be 20 MB or smaller.`);
          continue;
        }
        if (!this.attachments.some((item) => item.name === file.name && item.size === file.size)) {
          this.attachments.push(file);
        }
      }
      this.renderAttachments();
    }

    renderAttachments() {
      const container = document.getElementById("attachment-list");
      if (!container) return;
      container.innerHTML = "";
      this.attachments.forEach((file, index) => {
        const row = document.createElement("div");
        row.className = "attachment-row";
        const status = file.name.toLowerCase().endsWith(".doc") ? "warning" : "OK";
        const note = status === "warning" ? "Could not read this .doc file; save it as .docx or PDF" : "";
        row.innerHTML = `<span title="${escapeHTML(note)}">${escapeHTML(file.name)} (${(file.size / 1024).toFixed(1)} KB) <strong>${escapeHTML(status)}</strong>${note ? ` — ${escapeHTML(note)}` : ""}</span>`;
        const remove = document.createElement("button");
        remove.className = "btn-tool";
        remove.textContent = "Remove";
        remove.onclick = () => {
          this.attachments.splice(index, 1);
          this.renderAttachments();
        };
        row.appendChild(remove);
        container.appendChild(row);
      });
    }

    saveProblemDraft() {
      const statement = document.getElementById("input-problem")?.value || "";
      const cap = parseFloat(document.getElementById("input-run-budget-cap")?.value || "7");
      if (!statement.trim() && this.attachments.length === 0) {
        alert("Enter a problem statement or attach a document.");
        return;
      }
      this.draftProblem = { statement, cap, attachments: this.attachments.slice() };
      this.closeModals();
      this.updateProblemStatus(statement);
    }

    updateProblemStatus(statement) {
      const title = (statement || "").split(/\r?\n/)[0].trim();
      const label = title ? title.substring(0, 60) : "Ready";
      const main = document.getElementById("status-main-label");
      const badge = document.getElementById("badge-problem");
      if (main) main.textContent = label;
      if (badge) badge.textContent = label;
    }
  populateRunData(data) {
    this.currentRunId = data.run ? data.run.run_id : "loaded_run";

    const rawNodes = data.nodes || [];
    const normalizedNodes = rawNodes.map((n) => {
      const node = { ...n };
      if (!node.id && node.node_id) node.id = node.node_id;
      if (!node.parents || node.parents.length === 0) {
        if (node.parents_json) {
          try { node.parents = JSON.parse(node.parents_json); } catch (e) { node.parents = []; }
        } else {
          node.parents = [];
        }
      }
      if (!node.output && node.output_json) {
        try { node.output = JSON.parse(node.output_json); } catch (e) { node.output = {}; }
      }
      if (!node.analysis && node.analysis_json) {
        try { node.analysis = JSON.parse(node.analysis_json); } catch (e) { node.analysis = null; }
      }
      if (!node.rollouts && node.rollouts_json) {
        try { node.rollouts = JSON.parse(node.rollouts_json); } catch (e) { node.rollouts = []; }
      }
      if (!node.falsifier_report && node.falsifier_report_json) {
        try { node.falsifier_report = JSON.parse(node.falsifier_report_json); } catch (e) { node.falsifier_report = null; }
      }
      return node;
    });

    this.currentRunData = {
      nodes: normalizedNodes,
      edges: data.edges || [],
      events: data.events || [],
      assembled_latex: data.assembled_latex || (data.run ? data.run.assembled_latex : "") || "",
      knowledge_directory: data.knowledge_directory || [],
      hmed_records: data.hmed_records || [],
    };

    const problem = (data.run ? data.run.problem : "") || "Mathematical Research Problem";
    const bp = document.getElementById("badge-problem");
    if (bp) bp.textContent = `Theorem: ${problem.substring(0, 45)}...`;

    const stream = document.getElementById("event-log-stream");
    if (stream) {
      stream.innerHTML = "";
      (data.events || []).forEach((ev) => {
        if (ev.event_type === "log_line") {
          this.appendLogEntry(ev.timestamp, ev.payload.stage, ev.payload.severity, ev.payload.text, ev.payload.node_id);
        }
      });
    }

    this.updateGraphs();
    this.updateStatusMetrics();
    this.renderDocument();

    if (this.currentRunData.nodes.length > 0) {
      // Replay lands on the Script view so the saved math is visible at once.
      const firstSolver = this.currentRunData.nodes.find((n) => n.type === "solver" || n.stage === "solving");
      this.selectNode(firstSolver || this.currentRunData.nodes[0]);
      this.switchTab("doc");
    }
  }

  async triggerReexplore() {
    if (!this.currentRunId) {
      alert("No active run to re-explore.");
      return;
    }
    await this.runCommand("Re-explore", `/api/runs/${this.currentRunId}/reexplore`);
  }

  exportDirect(type) {
    if (!this.currentRunId) {
      alert("No active run to export.");
      return;
    }
    const tokenQuery = this.sessionToken ? `?token=${encodeURIComponent(this.sessionToken)}` : "";
    window.open(`/api/runs/${this.currentRunId}/export/${type}${tokenQuery}`, "_blank");
  }

  triggerImportJsonl() {
    let input = document.getElementById("input-import-jsonl");
    if (!input) {
      input = document.createElement("input");
      input.type = "file";
      input.id = "input-import-jsonl";
      input.accept = ".jsonl";
      input.style.display = "none";
      input.onchange = (e) => this.handleFileImportJsonl(e);
      document.body.appendChild(input);
    }
    input.click();
  }

  async handleFileImportJsonl(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
      const content = e.target.result;
      try {
        const res = await fetch("/api/traces/import_jsonl", {
          method: "POST",
          headers: { "Content-Type": "text/plain" },
          body: content,
        });
        const resp = await res.json();
        if (resp.status === "imported" && resp.run_id) {
          await this.loadRunTrace(resp.run_id);
          this.appendLogEntry(
            new Date().toTimeString().slice(0, 8),
            "all",
            "info",
            `Opened saved run: ${resp.run_id}`
          );
        }
      } catch (err) {
        alert(`Could not open that saved run: ${err}`);
      }
    };
    reader.readAsText(file);
    // Reset file input
    event.target.value = "";
  }

  async openRunHistoryModal() {
    try {
      const res = await fetch("/api/runs");
      const runs = await res.json();
      const container = document.getElementById("history-runs-list");
      if (!container) return;
      if (!runs || runs.length === 0) {
        container.innerHTML = `<div style="padding: 10px; color: #888;">No previous runs yet.</div>`;
      } else {
        container.innerHTML = runs
          .map(
            (r) => `
          <div class="coq-msg-line" style="padding: 6px; cursor: pointer;" onclick="window.app.loadRunTrace('${escapeHTML(r.run_id)}')">
            <strong>${escapeHTML(r.run_id)}</strong> - <span style="color:#007700; font-weight:bold;">[${escapeHTML((r.status || "").toUpperCase())}]</span>
            <div><em>${escapeHTML((r.problem || "").substring(0, 75))}...</em></div>
            <div style="font-size: 10px; color: #666;">Date: ${escapeHTML(r.created_at || "")} | Cost: $${(r.cost_usd || 0).toFixed(4)} | Meta: $${(r.cost_meta_usd || 0).toFixed(4)} | Baseten: $${(r.cost_baseten_usd || 0).toFixed(4)}</div>
            <button class="btn-tool" style="margin-top: 4px;" onclick="event.stopPropagation(); window.app.deleteRun('${escapeHTML(r.run_id)}')">Delete</button>
            ${["cancelled", "unresolved", "failed"].includes((r.status || "").toLowerCase()) ? '<button class="btn-tool" style="margin-top: 4px;" onclick="event.stopPropagation(); window.app.continueRun(\'' + escapeHTML(r.run_id) + '\', ' + (r.cost_usd || 0) + ')">Continue</button>' : ""}
          </div>
        `
          )
          .join("");
      }
      this.showModal("modal-run-history");
    } catch (e) {
      alert(`Failed to load history: ${e}`);
    }
  }

  async deleteRun(runId) {
    if (!confirm(`Delete saved run ${runId}? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/runs/${runId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      if (this.currentRunId === runId) {
        this.currentRunId = null;
        this.currentRunData = { nodes: [], edges: [], events: [], assembled_latex: "", knowledge_directory: [], hmed_records: [] };
        this.renderDocument();
      }
      await this.openRunHistoryModal();
    } catch (e) {
      alert(`Failed to delete run: ${e.message || e}`);
    }
  }

  async continueRun(runId, priorCost) {
    const capInput = prompt(
      `Continue run ${runId}? Already-written sections are reused; only the missing sections are solved, then the proof is verified.\n\nPrior spend: $${(priorCost || 0).toFixed(2)} (counts toward the cap).\nEnter the TOTAL budget cap in USD for this run:`,
      ((priorCost || 0) + 10).toFixed(2)
    );
    if (capInput === null) return;
    const budgetCap = parseFloat(capInput);
    if (!budgetCap || budgetCap <= (priorCost || 0)) {
      alert("Budget cap must be a number greater than the prior spend.");
      return;
    }
    try {
      const res = await fetch(`/api/runs/${runId}/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ budget_cap_usd: budgetCap }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Continue failed (${res.status})`);
      this.currentRunId = runId;
      this.closeModals();
      alert(`Continuing run ${runId}: reusing sections [${(data.reused_sections || []).join(", ")}], solving sections [${(data.missing_sections || []).join(", ")}].`);
    } catch (e) {
      alert(`Failed to continue run: ${e.message || e}`);
    }
  }

  async loadRunTrace(runId) {
    try {
      const res = await fetch(`/api/runs/${runId}`);
      const data = await res.json();
      this.populateRunData(data);
      this.closeModals();
    } catch (e) {
      alert(`Failed to load trace: ${e}`);
    }
  }

  async openSettingsModal() {
    await this.loadSettingsIntoUI();
    this.showModal("modal-settings");
  }

  async handleSaveSettings() {
    const metaKey = document.getElementById("input-api-key")?.value || "";
    const metaUrl = document.getElementById("input-base-url")?.value || "https://api.meta.ai/v1";
    const basetenKey = document.getElementById("input-baseten-key")?.value || "";
    const basetenUrl = document.getElementById("input-baseten-url")?.value || "https://inference.baseten.co/v1";
    const cap = parseFloat(document.getElementById("input-budget-cap")?.value) || 7.0;
    const reasoningEffort = document.getElementById("input-reasoning-effort")?.value || "medium";
    const concurrency = parseInt(document.getElementById("input-concurrency")?.value, 10) || 4;
    const fallbackEnabled = Boolean(document.getElementById("input-baseten-fallback")?.checked);
    const fireworksKey = document.getElementById("input-fireworks-key")?.value || "";
    const fireworksUrl = document.getElementById("input-fireworks-url")?.value || "https://api.fireworks.ai/inference/v1";
    const fireworksEnabled = Boolean(document.getElementById("input-fireworks-fallback")?.checked);

    const models = {
      explorer: document.getElementById("input-model-explorer")?.value || "muse-spark-1.3",
      falsifier: document.getElementById("input-model-falsifier")?.value || "muse-wonder-1.0",
      aggregator: document.getElementById("input-model-aggregator")?.value || "muse-spark-1.3",
      decomposer: document.getElementById("input-model-decomposer")?.value || "muse-wonder-1.0",
      solver: document.getElementById("input-model-solver")?.value || "muse-spark-1.3",
      global_verifier: document.getElementById("input-model-verifier")?.value || "muse-wonder-1.0",
    };

    const payload = {
      base_url: metaUrl,
      baseten_base_url: basetenUrl,
      default_budget_cap: cap,
      reasoning_effort: reasoningEffort,
      concurrency_limit: concurrency,
      default_models: models,
      baseten_fallback_enabled: fallbackEnabled,
      fireworks_base_url: fireworksUrl,
      fireworks_fallback_enabled: fireworksEnabled,
    };
    if (metaKey.trim()) payload.api_key = metaKey.trim();
    if (basetenKey.trim()) payload.baseten_api_key = basetenKey.trim();
    if (fireworksKey.trim()) payload.fireworks_api_key = fireworksKey.trim();

    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `Server error (${response.status})`);
      }
      alert("Settings saved successfully.");
      this.closeModals();
      await this.checkFirstRunKeySetup();
    } catch (e) {
      alert(`Error saving settings: ${e.message || e}`);
    }
  }

  /**
   * First-Run Key Setup check (FR8, Section 5.2, Section 9.5).
   * Prompts user for API keys on software startup.
   */
  async checkFirstRunKeySetup() {
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) {
        this.showModal("modal-first-run-setup");
        return;
      }
      const settings = await res.json();
      this.keysConfigured = Boolean(settings.api_key_set);

      const metaState = settings.api_key_set ? "ACTIVE" : "OFFLINE";
      let basetenState = "OFFLINE";
      if (settings.baseten_api_key_set && settings.baseten_fallback_enabled) {
        basetenState = "ACTIVE";
      } else if (settings.baseten_api_key_set) {
        basetenState = "CONFIGURED";
      }

      let fireworksState = "OFFLINE";
      if (settings.fireworks_api_key_set && settings.fireworks_fallback_enabled) {
        fireworksState = "ACTIVE";
      } else if (settings.fireworks_api_key_set) {
        fireworksState = "CONFIGURED";
      }
      const provider = document.getElementById("reference-provider");
      if (provider) provider.innerHTML = `Meta <b>[${metaState}]</b> · Baseten <b>[${basetenState}]</b> · Fireworks <b>[${fireworksState}]</b>`;
      const fwStatus = document.getElementById("fireworks-status");
      this.refreshBudgetFromServer(true);

      // Pre-fill existing settings if available
      if (settings.api_key_masked) {
        const inp = document.getElementById("setup-input-api-key");
        if (inp && !inp.value) inp.placeholder = `Configured: ${settings.api_key_masked}`;
      }
      if (settings.baseten_api_key_masked) {
        const inp = document.getElementById("setup-input-baseten-key");
        if (inp && !inp.value) inp.placeholder = `Configured: ${settings.baseten_api_key_masked}`;
      }
      const cb = document.getElementById("setup-checkbox-baseten-fallback");
      if (cb) {
        cb.checked = Boolean(settings.baseten_fallback_enabled);
      }
      if (settings.fireworks_api_key_masked) {
        const inp = document.getElementById("setup-input-fireworks-key");
        if (inp && !inp.value) inp.placeholder = `Configured: ${settings.fireworks_api_key_masked}`;
      }
      const fcb = document.getElementById("setup-checkbox-fireworks-fallback");
      if (fcb) {
        fcb.checked = Boolean(settings.fireworks_fallback_enabled);
      }

      if (!settings.api_key_set) {
        this.showModal("modal-first-run-setup");
      }
      this.updateKeySaveState();
    } catch (e) {
      console.warn("First run key setup check skipped:", e);
      this.showModal("modal-first-run-setup");
    }
  }

  async handleSaveFirstRunKeys() {
    const metaKey = document.getElementById("setup-input-api-key")?.value.trim() || "";
    const basetenKey = document.getElementById("setup-input-baseten-key")?.value.trim() || "";
    const fallbackCb = document.getElementById("setup-checkbox-baseten-fallback");
    const fallbackEnabled = fallbackCb ? fallbackCb.checked : false;
    const fireworksKey = document.getElementById("setup-input-fireworks-key")?.value.trim() || "";
    const fireworksCb = document.getElementById("setup-checkbox-fireworks-fallback");
    const fireworksEnabled = fireworksCb ? fireworksCb.checked : false;

    const clearErrors = () => {
      ["meta", "baseten", "fireworks"].forEach((provider) => {
        const element = document.getElementById(`setup-${provider}-error`);
        if (element) element.textContent = "";
      });
    };
    clearErrors();

    if (!metaKey && !this.keysConfigured) {
      const metaErr = document.getElementById("setup-meta-error");
      if (metaErr) metaErr.textContent = "Meta API key is required.";
      return;
    }

    try {
      // 1. Verify if credentials changed
      let basetenKeyToStore = basetenKey;
      let fallbackToStore = fallbackEnabled;
      let fireworksKeyToStore = fireworksKey;
      let fireworksToStore = fireworksEnabled;
      if (metaKey || basetenKey || fireworksKey) {
        const verify = await fetch("/api/keys/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            api_key: metaKey,
            baseten_api_key: basetenKey || null,
            baseten_fallback_enabled: fallbackEnabled,
            fireworks_api_key: fireworksKey || null,
            fireworks_fallback_enabled: fireworksEnabled,
          }),
        });
        const result = await verify.json();
        if (!verify.ok) {
          Object.entries(result.errors || {}).forEach(([provider, message]) => {
            const element = document.getElementById(`setup-${provider}-error`);
            if (element) element.textContent = message;
          });
          return;
        }
        if (result.warnings && result.warnings.baseten) {
          const element = document.getElementById("setup-baseten-error");
          if (element) element.textContent = result.warnings.baseten;
          basetenKeyToStore = "";
          fallbackToStore = false;
        }
        if (result.warnings && result.warnings.fireworks) {
          const element = document.getElementById("setup-fireworks-error");
          if (element) element.textContent = result.warnings.fireworks;
          fireworksKeyToStore = "";
          fireworksToStore = false;
        }
      }

      // 2. Persist
      const store = await fetch("/key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: metaKey || undefined,
          baseten_api_key: basetenKeyToStore,
          baseten_fallback_enabled: fallbackToStore,
          clear_baseten: basetenKeyToStore === "",
          fireworks_api_key: fireworksKeyToStore,
          fireworks_fallback_enabled: fireworksToStore,
          clear_fireworks: fireworksKeyToStore === "",
        }),
      });
      if (!store.ok) throw new Error("Key storage failed.");

      this.keysConfigured = true;
      this.closeModals();
      await this.checkFirstRunKeySetup();
    } catch (e) {
      const metaErr = document.getElementById("setup-meta-error");
      if (metaErr) metaErr.textContent = `Verification error: ${e.message || e}`;
    }
  }

  updateKeySaveState() {
    const meta = document.getElementById("setup-input-api-key")?.value.trim();
    const button = document.getElementById("btn-save-first-run");
    if (button) button.disabled = !meta && !this.keysConfigured;
  }

  showModal(id) {
    if (id !== "modal-first-run-setup" || this.keysConfigured) {
      document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
    }
    document.getElementById(id)?.classList.add("active");
    if (id === "modal-first-run-setup") this.updateKeySaveState();
  }

  async loadSettingsIntoUI() {
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) throw new Error(`Settings request failed (${res.status})`);
      const settings = await res.json();
      const values = {
        "input-base-url": settings.base_url,
        "input-baseten-url": settings.baseten_base_url,
        "input-baseten-fallback": Boolean(settings.baseten_fallback_enabled),
        "input-fireworks-url": settings.fireworks_base_url,
        "input-fireworks-fallback": Boolean(settings.fireworks_fallback_enabled),
        "input-budget-cap": settings.default_budget_cap,
        "input-reasoning-effort": settings.reasoning_effort,
        "input-concurrency": settings.concurrency_limit,
        "input-model-explorer": settings.default_models?.explorer,
        "input-model-falsifier": settings.default_models?.falsifier,
        "input-model-aggregator": settings.default_models?.aggregator,
        "input-model-decomposer": settings.default_models?.decomposer,
        "input-model-solver": settings.default_models?.solver,
        "input-model-verifier": settings.default_models?.global_verifier,
      };
      Object.entries(values).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (!element || value === undefined || value === null) return;
        if (element.type === "checkbox") {
          element.checked = Boolean(value);
        } else {
          element.value = value;
        }
      });

      const metaKeyInput = document.getElementById("input-api-key");
      if (metaKeyInput) {
        metaKeyInput.value = "";
        if (settings.api_key_masked) {
          metaKeyInput.placeholder = `Configured: ${settings.api_key_masked}`;
        }
      }

      const fireworksKeyInput = document.getElementById("input-fireworks-key");
      if (fireworksKeyInput) {
        fireworksKeyInput.value = "";
        if (settings.fireworks_api_key_masked) {
          fireworksKeyInput.placeholder = `Configured: ${settings.fireworks_api_key_masked}`;
        }
      }

      const basetenKeyInput = document.getElementById("input-baseten-key");
      if (basetenKeyInput) {
        basetenKeyInput.value = "";
        if (settings.baseten_api_key_masked) {
          basetenKeyInput.placeholder = `Configured: ${settings.baseten_api_key_masked}`;
        }
      }
    } catch (error) {
      console.error("Could not load settings:", error);
    }
  }

  closeModals() {
    if (document.getElementById("modal-first-run-setup")?.classList.contains("active") && !this.keysConfigured) {
      return;
    }
    document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
  }

  /**
   * Step Forward: advance replay by one event / stage boundary (FR4, FR5).
   * In live mode, sends a step command to the backend.
   * In replay mode, advances the replay index by one event.
   */
  stepForward() {
    if (this.isReplayMode && this.replayEvents.length > 0) {
      if (this.replayIndex < this.replayEvents.length - 1) {
        this.replayIndex++;
        this._applyReplayUpTo(this.replayIndex);
        this.appendLogEntry(
          new Date().toTimeString().slice(0, 8), "all", "info",
          `[Replay] Step forward to event ${this.replayIndex + 1}/${this.replayEvents.length}`
        );
      } else {
        this.appendLogEntry(
          new Date().toTimeString().slice(0, 8), "all", "warning",
          "[Replay] Already at the last event."
        );
      }
    } else {
      // Live mode: send step command to backend (with feedback/timeout)
      this.runCommand("Step", "/api/runs/step");
      this.appendLogEntry(
        new Date().toTimeString().slice(0, 8), "all", "info",
        "Step: pausing at next stage boundary..."
      );
    }
  }

  /**
   * Step Back: go back one event in replay (FR5).
   * In live mode, switches to replay mode and shows the previous state.
   */
  stepBack() {
    // If we have events, enter replay mode
    if (this.currentRunData.events && this.currentRunData.events.length > 0) {
      if (!this.isReplayMode) {
        // Enter replay mode from live view
        this.isReplayMode = true;
        this.replayEvents = [...this.currentRunData.events];
        this.replayIndex = this.replayEvents.length - 2; // Go back one
        if (this.replayIndex < 0) this.replayIndex = 0;
      } else {
        this.replayIndex = Math.max(0, this.replayIndex - 1);
      }
      this._applyReplayUpTo(this.replayIndex);
      this.appendLogEntry(
        new Date().toTimeString().slice(0, 8), "all", "info",
        `[Replay] Step back to event ${this.replayIndex + 1}/${this.replayEvents.length}`
      );
    } else {
      this.appendLogEntry(
        new Date().toTimeString().slice(0, 8), "all", "warning",
        "No events to step back through."
      );
    }
  }

  /**
   * Run to End: jump to the final state in replay mode (FR5).
   */
  runToEnd() {
    if (this.isReplayMode && this.replayEvents.length > 0) {
      this.replayIndex = this.replayEvents.length - 1;
      this._applyReplayUpTo(this.replayIndex);
      this.isReplayMode = false;
      this.appendLogEntry(
        new Date().toTimeString().slice(0, 8), "all", "info",
        `[Replay] Jumped to final state (${this.replayEvents.length} events).`
      );
    } else if (!this.isReplayMode) {
      this.appendLogEntry(
        new Date().toTimeString().slice(0, 8), "all", "info",
        "Not in replay mode. Use Step Back first to enter replay."
      );
    }
  }

  /**
   * Internal: rebuild the view from events 0..index.
   * Pure reducer: view = reduce(events[0..n]) per Section 5.3.
   */
  _applyReplayUpTo(index) {
    const events = this.replayEvents.slice(0, index + 1);
    const replayData = window.reduceReplayEvents(events);
    // Apply the reconstructed state
    this.currentRunData = replayData;
    this.populateRunData(replayData);
    if (typeof window.graphRenderer !== "undefined" && window.graphRenderer) {
      window.graphRenderer.render(replayData.nodes, replayData.edges);
    }
    // Update proof pane
    this.renderDocument();
    this.updatePreviewProof();
  }

  async quit() {
    // Stop token spend first: halt the run, then shut the backend process down.
    try { await this.apiPost("/api/runs/stop"); } catch (e) { /* shutting down anyway */ }
    try { if (this.ws) this.ws.close(); } catch (e) { /* ignore */ }
    try {
      await fetch("/shutdown", { method: "POST", keepalive: true });
    } catch (e) { /* backend may already be gone */ }
    if (window.electronAPI && typeof window.electronAPI.quit === "function") {
      try { await window.electronAPI.quit(); } catch (e) { /* ignore */ }
    }
    window.close();
    setTimeout(() => {
      if (!window.closed) {
        document.body.innerHTML = '<div style="font-family: sans-serif; padding: 40px; font-size: 14px;">Mini-Colosseum has stopped. No more API calls will be made. You can close this tab.</div>';
      }
    }, 600);
  }

  setCommandBusy(label, busy) {
    document.querySelectorAll("[data-run-command]").forEach((b) => { b.disabled = busy; });
    const main = document.getElementById("status-main-label");
    if (main && busy) main.textContent = `${label}…`;
  }

  // Every run command gives instant feedback and reports timeouts instead
  // of silently hanging.
  async runCommand(label, url, timeoutMs = 12000) {
    this.setCommandBusy(label, true);
    this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "info", `${label} requested…`);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { method: "POST", signal: controller.signal });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Server error (${res.status})`);
      this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "info", `${label}: ${data.status || "done"}`);
      return data;
    } catch (e) {
      const msg = e.name === "AbortError"
        ? `${label} timed out after ${Math.round(timeoutMs / 1000)}s with no reply. It may still be working; check the messages below.`
        : `${label} failed: ${e.message || e}`;
      this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "error", msg);
      const stage = document.getElementById("status-stage-label");
      if (stage && e.name === "AbortError") stage.textContent = `Stage: ${label.toUpperCase()} TIMED OUT`;
      return null;
    } finally {
      clearTimeout(timer);
      this.setCommandBusy(label, false);
    }
  }

  async handlePause() { return this.runCommand("Pause", "/api/runs/pause"); }
  async handleStop() { return this.runCommand("Stop", "/api/runs/stop"); }

  async apiPost(url) {
    return this.runCommand("Command", url);
  }
}

window.MiniColosseumApp = MiniColosseumApp;

window.addEventListener("DOMContentLoaded", () => {
  try {
    window.app = new MiniColosseumApp();
  } catch (err) {
    console.error("CRITICAL MiniColosseumApp init failure:", err);
  }
});
