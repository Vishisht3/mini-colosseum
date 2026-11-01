/**
 * Mini-Colosseum Main Application Logic
 * Coordinates UI state, WebSocket live streaming, layout splitters,
 * modals, graph renderers, inspector, and event log.
 */

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
    };
    this.selectedNode = null;
    this.activeTab = "tree";
    this.startTime = null;
    this.timerInterval = null;
    this.filterStage = "all";
    this.filterSeverity = "all";

    // Replay mode state
    this.isReplayMode = false;
    this.replayEvents = [];
    this.replayIndex = 0;
    this.replayInterval = null;

    this.initDOM();
    this.initRenderers();
    this.initSplitters();
    this.initModals();
    this.connectWebSocket();
    this.loadDemoProblems();
    this.loadPastRuns();

    // Load initial clean success fixture by default so the app opens fully populated!
    this.loadFixture("clean_success");
  }

  initDOM() {
    // Toolbar buttons
    this.btnRun = document.getElementById("btn-run");
    this.btnPause = document.getElementById("btn-pause");
    this.btnStep = document.getElementById("btn-step");
    this.btnStop = document.getElementById("btn-stop");
    this.btnReexplore = document.getElementById("btn-reexplore");
    this.btnExport = document.getElementById("btn-export");
    this.btnNewRun = document.getElementById("btn-new-run");
    this.btnHistory = document.getElementById("btn-history");

    this.btnRun.addEventListener("click", () => this.showModal("modal-run-setup"));
    this.btnPause.addEventListener("click", () => this.apiPost("/api/runs/pause"));
    this.btnStep.addEventListener("click", () => this.apiPost("/api/runs/step"));
    this.btnStop.addEventListener("click", () => this.apiPost("/api/runs/stop"));
    this.btnReexplore.addEventListener("click", () => this.triggerReexplore());
    this.btnExport.addEventListener("click", () => this.showModal("modal-export"));
    this.btnNewRun.addEventListener("click", () => this.showModal("modal-run-setup"));
    this.btnHistory.addEventListener("click", () => this.openRunHistoryModal());

    // Menu bar items
    document.querySelectorAll(".menu-item").forEach((item) => {
      item.addEventListener("click", (e) => {
        const wasActive = item.classList.contains("active");
        document.querySelectorAll(".menu-item").forEach((m) => m.classList.remove("active"));
        if (!wasActive) item.classList.add("active");
        e.stopPropagation();
      });
    });

    window.addEventListener("click", () => {
      document.querySelectorAll(".menu-item").forEach((m) => m.classList.remove("active"));
    });

    // Menu actions
    document.getElementById("menu-new-run")?.addEventListener("click", () => this.showModal("modal-run-setup"));
    document.getElementById("menu-open-history")?.addEventListener("click", () => this.openRunHistoryModal());
    document.getElementById("menu-export-latex")?.addEventListener("click", () => this.exportDirect("latex"));
    document.getElementById("menu-export-json")?.addEventListener("click", () => this.exportDirect("json"));
    document.getElementById("menu-settings")?.addEventListener("click", () => this.showModal("modal-settings"));
    document.getElementById("menu-help-about")?.addEventListener("click", () => alert("Mini-Colosseum v1.0\nA research-harness workbench built on Meta Muse models\nBased on Stellar Colosseum (Lin, Woodruff et al., arXiv:2609.15983)"));

    // Tabs
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-tab");
        this.switchTab(tab);
      });
    });

    // Graph controls
    document.getElementById("btn-fit-tree")?.addEventListener("click", () => this.treeRenderer.fitToScreen());
    document.getElementById("btn-reset-tree")?.addEventListener("click", () => this.treeRenderer.resetZoom());
    document.getElementById("btn-fit-dag")?.addEventListener("click", () => this.dagRenderer.fitToScreen());
    document.getElementById("btn-reset-dag")?.addEventListener("click", () => this.dagRenderer.resetZoom());

    // Log filters
    document.getElementById("log-filter-stage")?.addEventListener("change", (e) => {
      this.filterStage = e.target.value;
      this.filterEventLogs();
    });
    document.getElementById("log-filter-severity")?.addEventListener("change", (e) => {
      this.filterSeverity = e.target.value;
      this.filterEventLogs();
    });

    // Document click to select section node
    document.getElementById("document-content")?.addEventListener("click", (e) => {
      const secEl = e.target.closest(".document-section");
      if (secEl) {
        const secIdx = parseInt(secEl.getAttribute("data-section-idx"), 10);
        const node = this.currentRunData.nodes.find(
          (n) => n.id === `SEC_${secIdx}` || n.label === `SEC_${secIdx}`
        );
        if (node) this.selectNode(node);
      }
    });
  }

  initRenderers() {
    this.treeContainer = document.getElementById("tree-canvas-container");
    this.dagContainer = document.getElementById("dag-canvas-container");
    this.docContainer = document.getElementById("document-content");

    this.treeRenderer = new GraphRenderer(this.treeContainer, (node) => this.selectNode(node));
    this.dagRenderer = new GraphRenderer(this.dagContainer, (node) => {
      this.selectNode(node);
      this.highlightDocumentSection(node);
    });
  }

  initSplitters() {
    // Horizontal splitter (between left and right panes)
    const resizerX = document.getElementById("resizer-x");
    const leftPane = document.getElementById("left-pane");
    let isResizingX = false;

    resizerX.addEventListener("mousedown", (e) => {
      isResizingX = true;
      document.body.style.cursor = "col-resize";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizingX) return;
      const totalWidth = window.innerWidth;
      const newWidth = Math.max(300, Math.min(e.clientX, totalWidth - 300));
      leftPane.style.width = `${newWidth}px`;
    });

    window.addEventListener("mouseup", () => {
      if (isResizingX) {
        isResizingX = false;
        document.body.style.cursor = "default";
        this.treeRenderer.fitToScreen();
        this.dagRenderer.fitToScreen();
      }
    });

    // Vertical splitter (between Inspector and Event Log)
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
      const newHeight = Math.max(120, Math.min(e.clientY - rightPaneRect.top, rightPaneRect.height - 100));
      inspectorPane.style.height = `${newHeight}px`;
    });

    window.addEventListener("mouseup", () => {
      if (isResizingY) {
        isResizingY = false;
        document.body.style.cursor = "default";
      }
    });
  }

  initModals() {
    // Close modal handlers
    document.querySelectorAll(".btn-close-modal").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
      });
    });

    // Run Setup submit
    document.getElementById("btn-start-run")?.addEventListener("click", () => this.handleStartRun());

    // Settings save
    document.getElementById("btn-save-settings")?.addEventListener("click", () => this.handleSaveSettings());

    // Voice dictation emulation button
    document.getElementById("btn-dictate")?.addEventListener("click", () => this.handleDictation());

    // Problem select dropdown change
    document.getElementById("preset-problem-select")?.addEventListener("change", (e) => {
      const idx = e.target.value;
      if (this.demoProblems && this.demoProblems[idx]) {
        document.getElementById("input-problem").value = this.demoProblems[idx].statement;
      }
    });

    // Replay controls in modal
    document.getElementById("btn-replay-play")?.addEventListener("click", () => this.playReplay());
    document.getElementById("btn-replay-pause")?.addEventListener("click", () => this.pauseReplay());
    document.getElementById("btn-replay-step")?.addEventListener("click", () => this.stepReplay());
    document.getElementById("btn-replay-reset")?.addEventListener("click", () => this.resetReplay());
    document.getElementById("replay-slider")?.addEventListener("input", (e) => this.seekReplay(parseInt(e.target.value, 10)));
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "localhost:8765";
    const wsUrl = `${protocol}//${host}/ws`;

    this.updateStatusPill("connecting", "#d4a017");

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.updateStatusPill("connected", "#28a745");
        document.getElementById("status-connection").textContent = "Connected 🟢";
      };

      this.ws.onmessage = (event) => {
        try {
          const ev = JSON.parse(event.data);
          this.handleLiveEvent(ev);
        } catch (e) {
          console.error("WS Parse error:", e);
        }
      };

      this.ws.onclose = () => {
        this.updateStatusPill("disconnected", "#cb3837");
        document.getElementById("status-connection").textContent = "Offline (Replay ready) ⚪";
        setTimeout(() => this.connectWebSocket(), 3000);
      };
    } catch (e) {
      console.warn("WebSocket could not connect. Running offline mode.");
    }
  }

  updateStatusPill(state, color) {
    const pill = document.getElementById("status-pill");
    if (pill) pill.style.backgroundColor = color;
  }

  handleLiveEvent(ev) {
    this.currentRunData.events.push(ev);

    switch (ev.event_type) {
      case "round_started":
        document.getElementById("status-round").textContent = `Round ${ev.payload.round}`;
        break;

      case "stage_changed":
        document.getElementById("status-stage").textContent = `Stage: ${ev.payload.stage.toUpperCase()}`;
        if (ev.payload.stage === "solving") {
          // Auto switch to DAG tab when entering solving stage
          this.switchTab("dag");
        } else if (ev.payload.stage === "verification") {
          // Render document
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

      case "log_line":
        this.appendLogEntry(ev.timestamp, ev.payload.stage, ev.payload.severity, ev.payload.text, ev.payload.node_id);
        break;

      case "budget_warning":
        this.appendLogEntry(ev.timestamp, "all", "error", `BUDGET CAP REACHED: ${ev.payload.message}`);
        alert(`BUDGET WARNING: ${ev.payload.message}`);
        break;

      case "run_finished":
        this.currentRunData.assembled_latex = ev.payload.assembled_latex || this.currentRunData.assembled_latex;
        this.renderDocument();
        this.appendLogEntry(ev.timestamp, "all", "info", `Run finished. Status: ${ev.payload.status}. Assembled proof complete.`);
        clearInterval(this.timerInterval);
        break;
    }

    this.updateStatusMetrics();
  }

  updateGraphs() {
    // Exploration tree gets exploration nodes and aggregation edges
    const treeNodes = this.currentRunData.nodes.filter(
      (n) => n.stage === "exploration" || n.type === "explorer" || n.type === "aggregator" || n.type === "gate"
    );
    const treeEdges = this.currentRunData.edges.filter((e) => e.edge_type === "aggregation" || e.type === "aggregation");
    this.treeRenderer.setData(treeNodes, treeEdges, { collapsePriorRounds: true });

    // Proof DAG gets solving / section nodes and dependency edges
    const dagNodes = this.currentRunData.nodes.filter(
      (n) => n.stage === "solving" || n.type === "solver" || n.type === "decomposer"
    );
    const dagEdges = this.currentRunData.edges.filter((e) => e.edge_type === "dependency" || e.type === "dependency");
    this.dagRenderer.setData(dagNodes, dagEdges);
  }

  updateStatusMetrics() {
    let totalCost = 0;
    let totalIn = 0;
    let totalCached = 0;
    let totalOut = 0;
    let calls = this.currentRunData.nodes.length;

    this.currentRunData.nodes.forEach((n) => {
      totalCost += n.cost_usd || 0;
      totalIn += n.tokens_in || 0;
      totalCached += n.tokens_cached || 0;
      totalOut += n.tokens_out || 0;
    });

    document.getElementById("status-calls").textContent = `Calls ${calls}`;
    const totalTokK = Math.round((totalIn + totalOut) / 1000);
    const cachedTokK = Math.round(totalCached / 1000);
    document.getElementById("status-tokens").textContent = `${totalTokK}k tok (${cachedTokK}k cached)`;
    document.getElementById("status-cost").textContent = `$${totalCost.toFixed(4)} / $20.00`;
  }

  switchTab(tab) {
    this.activeTab = tab;
    document.querySelectorAll(".tab-btn").forEach((b) => {
      if (b.getAttribute("data-tab") === tab) b.classList.add("active");
      else b.classList.remove("active");
    });
    document.querySelectorAll(".tab-content").forEach((c) => {
      if (c.id === `tab-${tab}`) c.classList.add("active");
      else c.classList.remove("active");
    });

    if (tab === "tree") this.treeRenderer.fitToScreen();
    if (tab === "dag") this.dagRenderer.fitToScreen();
    if (tab === "doc") this.renderDocument();
  }

  selectNode(node) {
    if (!node) return;
    this.selectedNode = node;
    this.treeRenderer.setSelectedNode(node.id);
    this.dagRenderer.setSelectedNode(node.id);

    // Populate Inspector (Section 6.4)
    document.getElementById("insp-id").textContent = node.id || "-";
    document.getElementById("insp-label").textContent = node.label || "-";
    document.getElementById("insp-type").textContent = node.type || "-";
    document.getElementById("insp-stage").textContent = `${node.stage || "-"} (Round ${node.round || 1})`;

    const statusStyle = this.treeRenderer.getStatusStyle(node.status);
    const statusEl = document.getElementById("insp-status");
    statusEl.textContent = `[${statusStyle.glyph}] ${node.status.toUpperCase()}`;
    statusEl.className = `tag-badge`;
    statusEl.style.backgroundColor = statusStyle.bg;
    statusEl.style.borderColor = statusStyle.border;
    statusEl.style.color = statusStyle.text;

    document.getElementById("insp-model").textContent = node.model || "muse-spark-1.3";
    document.getElementById("insp-tokens").textContent = `In: ${node.tokens_in || 0} (${node.tokens_cached || 0} cached) | Out: ${node.tokens_out || 0}`;
    document.getElementById("insp-cost").textContent = `$${(node.cost_usd || 0).toFixed(6)}`;

    // Parents / Children links
    const parentsHtml = (node.parents || []).map((pid) => `<a href="#" class="node-link" data-id="${pid}">${pid}</a>`).join(", ") || "None (leaf)";
    document.getElementById("insp-parents").innerHTML = parentsHtml;

    // Subgoal 1: Input
    document.getElementById("insp-input-content").textContent = node.input_summary || "Standard prompt from research coordinator.";

    // Subgoal 2: Output
    const outJson = JSON.stringify(node.output || {}, null, 2);
    document.getElementById("insp-output-content").textContent = outJson;

    // Subgoal 3: Falsifier Report
    if (node.falsifier_report) {
      const f = node.falsifier_report;
      let fText = `Verdict: ${f.verdict}\nAssessment: ${f.assessment}\n`;
      if (f.weakest_lemmas && f.weakest_lemmas.length) {
        fText += `Weakest Lemmas: ${f.weakest_lemmas.join(", ")}\n`;
      }
      if (f.categorized_objections && f.categorized_objections.length) {
        fText += `Objections: ${JSON.stringify(f.categorized_objections, null, 2)}\n`;
      }
      document.getElementById("insp-falsifier-content").textContent = fText;
    } else {
      document.getElementById("insp-falsifier-content").textContent = "No falsifier report attached.";
    }

    // Subgoal 4: Unresolved Objections
    const objs = node.objections || [];
    document.getElementById("insp-objections-content").textContent = objs.length > 0 ? JSON.stringify(objs, null, 2) : "None (All objections addressed).";

    // Attach click events on parents
    document.querySelectorAll(".node-link").forEach((link) => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const pId = link.getAttribute("data-id");
        const pNode = this.currentRunData.nodes.find((n) => n.id === pId);
        if (pNode) this.selectNode(pNode);
      });
    });
  }

  highlightDocumentSection(node) {
    if (node.stage === "solving" || node.type === "solver") {
      const secIdx = parseInt(node.id.replace("SEC_", ""), 10);
      const secEl = document.querySelector(`.document-section[data-section-idx="${secIdx}"]`);
      if (secEl) {
        secEl.scrollIntoView({ behavior: "smooth", block: "center" });
        secEl.style.outline = "2px solid #000000";
        setTimeout(() => (secEl.style.outline = "none"), 2000);
      }
    }
  }

  renderDocument() {
    const secNodes = this.currentRunData.nodes.filter((n) => n.type === "solver" || n.stage === "solving");
    const verifNode = this.currentRunData.nodes.find((n) => n.type === "global_verifier");
    const defects = verifNode && verifNode.output ? verifNode.output.defects || [] : [];

    const rendered = SimpleLaTeXRenderer.renderDocument(
      this.currentRunData.assembled_latex,
      secNodes,
      defects
    );
    this.docContainer.innerHTML = rendered;
  }

  appendLogEntry(timestamp, stage, severity, text, nodeId = null) {
    const stream = document.getElementById("event-log-stream");
    const entry = document.createElement("div");
    entry.className = `log-entry severity-${severity}`;
    entry.setAttribute("data-stage", stage);
    entry.setAttribute("data-severity", severity);
    if (nodeId) entry.setAttribute("data-node-id", nodeId);

    entry.innerHTML = `<span class="log-time">[${timestamp}]</span> <strong>[${stage.toUpperCase()}]</strong> ${text}`;

    if (nodeId) {
      entry.addEventListener("click", () => {
        const n = this.currentRunData.nodes.find((x) => x.id === nodeId);
        if (n) this.selectNode(n);
      });
    }

    stream.appendChild(entry);
    stream.scrollTop = stream.scrollHeight;
  }

  filterEventLogs() {
    const entries = document.querySelectorAll(".log-entry");
    entries.forEach((el) => {
      const st = el.getAttribute("data-stage");
      const sev = el.getAttribute("data-severity");
      const matchStage = this.filterStage === "all" || st === this.filterStage;
      const matchSev = this.filterSeverity === "all" || sev === this.filterSeverity;
      el.style.display = matchStage && matchSev ? "block" : "none";
    });
  }

  showModal(modalId) {
    document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add("active");
  }

  async loadDemoProblems() {
    try {
      const res = await fetch("/api/problems");
      this.demoProblems = await res.json();
      const select = document.getElementById("preset-problem-select");
      if (select) {
        select.innerHTML = '<option value="">-- Choose a pre-tested problem lemma --</option>';
        this.demoProblems.forEach((p, idx) => {
          select.innerHTML += `<option value="${idx}">${p.title}</option>`;
        });
      }
    } catch (e) {
      // Offline fallback
    }
  }

  async loadPastRuns() {
    try {
      const res = await fetch("/api/runs");
      const runs = await res.json();
      const container = document.getElementById("history-runs-list");
      if (!container) return;
      if (!runs || runs.length === 0) {
        container.innerHTML = `<div style="padding: 10px; color: #888;">No saved runs found.</div>`;
        return;
      }
      container.innerHTML = runs
        .map(
          (r) => `
        <div class="log-entry" style="padding: 6px; border-bottom: 1px solid #ccc; cursor: pointer;" onclick="window.app.loadRunTrace('${r.run_id}')">
          <strong>${r.run_id}</strong> - <span class="tag-badge">[${r.status.toUpperCase()}]</span>
          <div><em>${r.problem.substring(0, 70)}...</em></div>
          <div style="font-size: 10px; color: #666;">Date: ${r.created_at} | Cost: $${(r.cost_usd || 0).toFixed(4)} | Tokens: ${r.tokens_in + r.tokens_out}</div>
        </div>
      `
        )
        .join("");
    } catch (e) {
      // Offline
    }
  }

  async loadFixture(fixtureName) {
    try {
      const res = await fetch(`/api/fixtures/${fixtureName}`);
      const data = await res.json();
      this.populateRunData(data);
      this.appendLogEntry(
        "12:00:00",
        "all",
        "info",
        `Loaded recorded fixture: fixture_${fixtureName}.json for demonstration and inspection.`
      );
    } catch (e) {
      console.error("Failed to load fixture:", e);
    }
  }

  async loadRunTrace(runId) {
    try {
      const res = await fetch(`/api/runs/${runId}`);
      const data = await res.json();
      this.populateRunData(data);
      document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
    } catch (e) {
      alert(`Failed to load trace: ${e}`);
    }
  }

  populateRunData(data) {
    this.currentRunId = data.run ? data.run.run_id : "loaded_run";
    this.currentRunData = {
      nodes: data.nodes || [],
      edges: data.edges || [],
      events: data.events || [],
      assembled_latex: data.assembled_latex || (data.run ? data.run.assembled_latex : "") || "",
      knowledge_directory: data.knowledge_directory || [],
    };

    const problem = (data.run ? data.run.problem : "") || "Mathematical Research Problem";
    document.getElementById("badge-problem").textContent = `Problem: ${problem}`;

    // Clear logs and re-populate
    const stream = document.getElementById("event-log-stream");
    stream.innerHTML = "";
    (data.events || []).forEach((ev) => {
      if (ev.event_type === "log_line") {
        this.appendLogEntry(ev.timestamp, ev.payload.stage, ev.payload.severity, ev.payload.text, ev.payload.node_id);
      }
    });

    this.updateGraphs();
    this.updateStatusMetrics();
    this.renderDocument();

    if (this.currentRunData.nodes.length > 0) {
      this.selectNode(this.currentRunData.nodes[0]);
    }
  }

  async handleStartRun() {
    const problem = document.getElementById("input-problem").value.trim();
    if (!problem) {
      alert("Please enter a mathematics or TCS problem statement.");
      return;
    }

    const preset = document.getElementById("select-preset").value;
    const budget = parseFloat(document.getElementById("input-budget").value) || 20.0;
    const crossModel = document.getElementById("checkbox-cross-model") ? document.getElementById("checkbox-cross-model").checked : true;
    const forceRetry = document.getElementById("checkbox-force-retry").checked;

    document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));

    // Reset current run UI
    this.currentRunData = { nodes: [], edges: [], events: [], assembled_latex: "", knowledge_directory: [] };
    document.getElementById("event-log-stream").innerHTML = "";
    document.getElementById("badge-problem").textContent = `Problem: ${problem}`;

    // Start timer
    this.startTime = Date.now();
    clearInterval(this.timerInterval);
    this.timerInterval = setInterval(() => {
      const elapsedSec = Math.floor((Date.now() - this.startTime) / 1000);
      const mm = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
      const ss = String(elapsedSec % 60).padStart(2, "0");
      document.getElementById("status-time").textContent = `${mm}:${ss}`;
    }, 1000);

    try {
      const res = await fetch("/api/runs/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          problem_statement: problem,
          size_preset: preset,
          budget_cap_usd: budget,
          cross_model_review: crossModel,
          force_section_retry: forceRetry,
        }),
      });
      const data = await res.json();
      this.currentRunId = data.run_id;
    } catch (e) {
      alert(`Failed to start run: ${e}`);
    }
  }

  handleDictation() {
    const input = document.getElementById("input-problem");
    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
      // Simulate Muse Voice Transcribe audio dictation
      input.value = "Prove that every planar graph with girth at least 5 has an independent set of size at least n / 3.";
      alert("Voice Dictation (Muse Voice Transcribe) simulation: dictated planar graph lemma into problem field.");
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.start();

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
    };
  }

  openRunHistoryModal() {
    this.loadPastRuns();
    this.showModal("modal-run-history");
  }

  exportDirect(type) {
    if (!this.currentRunId) {
      alert("No active run to export.");
      return;
    }
    window.open(`/api/runs/${this.currentRunId}/export/${type}`, "_blank");
  }

  async apiPost(url) {
    try {
      await fetch(url, { method: "POST" });
    } catch (e) {
      console.error(e);
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.app = new MiniColosseumApp();
});
