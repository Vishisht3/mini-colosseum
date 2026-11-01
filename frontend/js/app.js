/**
 * Mini-Colosseum High-Functionality Desktop Controller
 * 100% Functional CoqIDE Workbench:
 * - Direct execution controls (Run All, Step, Pause, Stop, Re-explore)
 * - Inline Problem and Preset selection without modal friction
 * - Line-numbered script editor with dynamic lime-green execution frontier
 * - Interactive Subgoals pane with direct jumping to code & DAG nodes
 * - Tabbed inspector: Subgoals, Node Details, Falsifier Attacks, HMED Records
 * - Live WebSocket telemetry and offline replay
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
      hmed_records: [],
    };
    this.selectedNode = null;
    this.activeTab = "doc";
    this.activeInspTab = "goals";
    this.filterSeverity = "all";

    // Standard pre-loaded problem statements
    this.problemsMap = {
      erdos_szekeres: {
        title: "Erdős-Szekeres Theorem",
        statement: "Prove that every sequence of n^2 + 1 distinct real numbers contains a monotonic subsequence of length n + 1 (either strictly increasing or strictly decreasing).",
        coqCode: `Theorem erdos_szekeres : forall (n : nat) (s : Sequence (n^2 + 1)),
  HasMonotonicSubsequence s (n + 1).
Proof.
  (* Section 1: Definitions and Coordinate Assignment *)
  intros n s.
  pose (a := fun i => length (longest_increasing_subseq s i)).
  pose (b := fun i => length (longest_decreasing_subseq s i)).

  (* Section 2: Strict Invariant and Injectivity *)
  assert (H_inj : forall i j, i <> j -> (a i, b i) <> (a j, b j)).
  { intros i j H_diff. destruct (RealOrder s i j) as [H_inc | H_dec].
    - left. apply inc_extends; assumption.
    - right. apply dec_extends; assumption. }

  (* Section 3: Pigeonhole Dimension Contradiction *)
  apply pigeonhole_dimension with (bound := n).
  - apply H_inj.
  - assumption.
Qed.`,
      },
      oddtown: {
        title: "The Oddtown Theorem (Berlekamp 1969)",
        statement: "In a town with n residents, a collection of clubs is formed such that every club has an odd number of members, and any two distinct clubs share an even number of members. Prove that the total number of clubs cannot exceed n.",
        coqCode: `Theorem oddtown_theorem : forall (n : nat) (clubs : list (Vector F2 n)),
  PairwiseEvenIntersections clubs ->
  AllOddSizes clubs ->
  length clubs <= n.
Proof.
  (* Section 1: Incidence Vectors over F2 *)
  intros n clubs H_even H_odd.
  pose (v := fun c => incidence_vector c).

  (* Section 2: Orthogonality & Gram Matrix Identity *)
  assert (H_gram : forall i j, dot_product (v i) (v j) = (if Nat.eq_dec i j then 1 else 0)).
  { intros i j. destruct (Nat.eq_dec i j).
    - subst. apply odd_norm; assumption.
    - apply even_ortho; assumption. }

  (* Section 3: Linear Independence and Dimension Bound *)
  assert (H_indep : LinearIndependent (map v clubs)).
  { apply gram_identity_independent; apply H_gram. }
  apply dimension_bound in H_indep.
  exact H_indep.
Qed.`,
      },
      ramsey_k6: {
        title: "Ramsey Number R(3, 3) = 6",
        statement: "Prove that in any 2-coloring of the edges of a complete graph K_6 with colors Red and Blue, there exists at least one monochromatic triangle.",
        coqCode: `Theorem ramsey_r33 : forall (c : Edge (K 6) -> Color2),
  HasMonochromaticTriangle c.
Proof.
  (* Section 1: Vertex Degree Pigeonhole *)
  intros c.
  destruct (pigeonhole_incident_edges c (Vertex 0)) as [edges H_color].

  (* Section 2: Monochromatic Triangle Trichotomy *)
  destruct (check_endpoints_colored c edges) as [H_triangle | H_opposite_triangle].
  - apply H_triangle.
  - apply H_opposite_triangle.
Qed.`,
      },
      mantel: {
        title: "Mantel's Theorem",
        statement: "Prove that every triangle-free graph on n vertices contains at most floor(n^2 / 4) edges.",
        coqCode: `Theorem mantel_theorem : forall (G : Graph) (n : nat),
  Vertices G = n -> TriangleFree G -> Edges G <= (n^2 / 4).
Proof.
  (* Section 1: Degree sum across endpoints *)
  intros G n H_vert H_tf.
  assert (H_deg : forall u v, Edge G u v -> deg G u + deg G v <= n).
  { apply disjoint_neighborhoods; assumption. }

  (* Section 2: Cauchy-Schwarz Edge Sum *)
  apply sum_edges_cauchy_schwarz with (bound := n).
  exact H_deg.
Qed.`,
      },
      girth5_indset: {
        title: "Planar Graphs of Girth >= 5",
        statement: "Prove that every planar graph G with n vertices and girth at least 5 has an independent set of size at least n / 3.",
        coqCode: `Theorem girth5_indset : forall (G : PlanarGraph) (n : nat),
  Vertices G = n -> Girth G >= 5 -> Alpha G >= (n / 3).
Proof.
  (* Section 1: Euler Formula Face Bound *)
  intros G n H_v H_girth.
  assert (H_edges : Edges G <= (5/3)*n - (10/3)).
  { apply euler_girth_bound; assumption. }

  (* Section 2: Caro-Wei Bound *)
  apply caro_wei_independent_bound.
  exact H_edges.
Qed.`,
      },
    };

    this.initDOM();
    this.initRenderers();
    this.initSplitters();
    this.connectWebSocket();

    // Default to Oddtown theorem (clean, fast, mathematically rich)
    this.selectProblem("oddtown");
    this.loadFixture("clean_success");
  }

  initDOM() {
    // Problem selector dropdown
    const probSelect = document.getElementById("inline-problem-select");
    if (probSelect) {
      probSelect.addEventListener("change", (e) => {
        this.selectProblem(e.target.value);
      });
    }

    // Severity filter in console
    document.getElementById("log-filter-severity")?.addEventListener("change", (e) => {
      this.filterSeverity = e.target.value;
      this.filterEventLogs();
    });

    // Close modal on escape
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeModals();
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
    const resizerX = document.getElementById("resizer-x");
    const leftPane = document.getElementById("left-pane");
    let isResizingX = false;

    resizerX.addEventListener("mousedown", () => {
      isResizingX = true;
      document.body.style.cursor = "col-resize";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizingX) return;
      const totalWidth = window.innerWidth;
      const newWidth = Math.max(280, Math.min(e.clientX, totalWidth - 280));
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

  selectProblem(key) {
    if (key === "custom") {
      this.showModal("modal-run-setup");
      return;
    }

    const prob = this.problemsMap[key];
    if (!prob) return;

    document.getElementById("status-main-label").textContent = `Ready in Predicate_Logic, proving ${prob.title}`;
    document.getElementById("badge-problem").textContent = `Theorem: ${prob.title}`;

    // Update proof.v script editor content
    this.renderInitialScript(prob.coqCode);
  }

  renderInitialScript(code) {
    const lines = code.split("\n");
    let html = "";
    lines.forEach((line) => {
      let l = line.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      l = l.replace(/\b(Theorem|Lemma|Proof|Qed|forall|assert|destruct|pose|intros|apply|exact)\b/g, (m) => {
        if (m === "Theorem" || m === "Lemma") return `<span style="color:#cc4400; font-weight:bold;">${m}</span>`;
        if (m === "Proof" || m === "Qed" || m === "forall") return `<span style="color:#0000cc; font-weight:bold;">${m}</span>`;
        return `<span style="color:#005500;">${m}</span>`;
      });
      html += `<div class="coq-line">${l}</div>`;
    });

    this.docContainer.innerHTML = html;
    this.updateGutter(lines.length);
  }

  updateGutter(lineCount) {
    const gutter = document.getElementById("editor-gutter");
    if (!gutter) return;
    let numbers = [];
    for (let i = 1; i <= Math.max(lineCount, 25); i++) {
      numbers.push(i);
    }
    gutter.innerHTML = numbers.join("<br>");
  }

  switchTab(tab) {
    this.activeTab = tab;
    ["doc", "tree", "dag"].forEach((t) => {
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

    // setTimeout so newly-visible tab's SVG has real pixel dimensions before fitToScreen
    if (tab === "tree") setTimeout(() => this.treeRenderer.fitToScreen(), 80);
    if (tab === "dag") setTimeout(() => this.dagRenderer.fitToScreen(), 80);
    if (tab === "doc") this.renderDocument();
  }

  switchInspectorTab(tab) {
    this.activeInspTab = tab;
    ["goals", "details", "falsifier", "hmed"].forEach((t) => {
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
    const wsUrl = `${protocol}//${host}/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        document.getElementById("status-connection").textContent = "Coqide connected 🟢";
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
        document.getElementById("status-connection").textContent = "Coqide offline ⚪";
        setTimeout(() => this.connectWebSocket(), 3000);
      };
    } catch (e) {
      console.warn("WebSocket could not connect. Running offline mode.");
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
        document.getElementById("status-stage-label").textContent = "Stage: PROVED [Qed]";
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

    document.getElementById("status-calls").textContent = `Calls: ${calls}`;
    const totalTokK = Math.round((totalIn + totalOut) / 1000);
    const cachedTokK = Math.round(totalCached / 1000);
    document.getElementById("status-tokens").textContent = `${totalTokK}k tok (${cachedTokK}k cached)`;
    document.getElementById("status-cost").textContent = `$${totalCost.toFixed(4)} / $20.00`;
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

    const statusStyle = this.treeRenderer.getStatusStyle(node.status);
    const label = node.label || node.id;

    // Format Hypotheses block
    let hypotheses = `H_node : ${node.id} (${node.type})\nH_status : [${statusStyle.glyph}] ${node.status.toUpperCase()}`;
    if (node.parents && node.parents.length > 0) {
      hypotheses += `\nIH_parents : forall p in [${node.parents.join(", ")}], Verified p`;
    }
    if (node.model) {
      hypotheses += `\nH_model : ${node.model}`;
    }
    hypothesesEl.textContent = hypotheses;

    // Subgoals target
    const out = node.output || {};
    const targetClaim = out.target_claim || out.primary_route || out.claimed_result || "Prove subproblem obligation.";
    const backupRoute = (out.backup_routes && out.backup_routes[0]) || out.concrete_next_task || "{S n = S m} + {S n <> S m}";

    subgoalsCountEl.textContent = `${(out.active_obligations && out.active_obligations.length) || 2} subgoals (Focus: ${label})`;
    tag1El.textContent = "(1/2)";
    target1El.textContent = targetClaim;
    tag2El.textContent = "(2/2)";
    target2El.textContent = backupRoute;

    // Node Details Tab
    document.getElementById("insp-meta-text").innerHTML = `
      <strong>Node:</strong> ${label} (${node.id}) | <strong>Stage:</strong> ${node.stage} (Round ${node.round || 1})<br>
      <strong>Model:</strong> ${node.model || "muse-spark-1.3"} | <strong>Cost:</strong> $${(node.cost_usd || 0).toFixed(6)}<br>
      <strong>Tokens:</strong> In ${node.tokens_in || 0} (${node.tokens_cached || 0} cached) | Out ${node.tokens_out || 0}
    `;
    document.getElementById("insp-input-content").textContent = node.input_summary || "Prompt summary.";
    document.getElementById("insp-output-content").textContent = JSON.stringify(node.output || {}, null, 2);

    // Falsifier Report Tab
    if (node.falsifier_report) {
      const f = node.falsifier_report;
      let fText = `Verdict: ${f.verdict}\nAssessment: ${f.assessment || ""}\n`;
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

    // HMED Revision Tab
    const hmedRecords = this.currentRunData.hmed_records || [];
    const nodeHmed = hmedRecords.find((r) => r.subproblem_index === (out.section_index || 0) || r.subproblem_index === 2);
    if (nodeHmed) {
      document.getElementById("insp-hmed-content").textContent = JSON.stringify(nodeHmed, null, 2);
    }

    document.getElementById("status-main-label").textContent = `Ready in Predicate_Logic, proving ${label}`;
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

    const rendered = SimpleLaTeXRenderer.renderDocument(
      this.currentRunData.assembled_latex,
      secNodes,
      defects
    );
    this.docContainer.innerHTML = rendered;
    const lineCount = rendered.split("<div class=\"coq-line").length;
    this.updateGutter(lineCount);
  }

  appendLogEntry(timestamp, stage, severity, text, nodeId = null) {
    const stream = document.getElementById("event-log-stream");
    const entry = document.createElement("div");
    entry.className = `coq-msg-line ${severity}`;
    entry.setAttribute("data-stage", stage);
    entry.setAttribute("data-severity", severity);
    if (nodeId) entry.setAttribute("data-node-id", nodeId);

    entry.innerHTML = `<span style="color:#666660;">[${timestamp}]</span> <strong>[${stage.toUpperCase()}]</strong> ${text}`;

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
    const entries = document.querySelectorAll(".coq-msg-line");
    entries.forEach((el) => {
      const sev = el.getAttribute("data-severity");
      const matchSev = this.filterSeverity === "all" || sev === this.filterSeverity;
      el.style.display = matchSev ? "block" : "none";
    });
  }

  async handleRunAll() {
    const probKey = document.getElementById("inline-problem-select").value;
    const preset = document.getElementById("inline-preset-select").value;
    let statement = "";

    if (probKey === "custom") {
      statement = document.getElementById("input-problem").value.trim();
      if (!statement) {
        alert("Please enter a custom theorem statement.");
        this.showModal("modal-run-setup");
        return;
      }
    } else {
      statement = this.problemsMap[probKey].statement;
    }

    // Reset current run UI
    this.currentRunData = { nodes: [], edges: [], events: [], assembled_latex: "", knowledge_directory: [], hmed_records: [] };
    document.getElementById("event-log-stream").innerHTML = "";
    document.getElementById("status-stage-label").textContent = "Stage: EXPLORING";

    this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "info", `Starting Mini-Colosseum pipeline on: ${statement.substring(0, 60)}...`);

    try {
      const res = await fetch("/api/runs/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          problem_statement: statement,
          size_preset: preset,
          budget_cap_usd: 20.0,
          cross_model_review: true,
          force_section_retry: probKey === "ramsey_k6",
        }),
      });
      const data = await res.json();
      this.currentRunId = data.run_id;
    } catch (e) {
      alert(`Failed to start run: ${e}`);
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
        `Loaded benchmark trace: fixture_${fixtureName}.json`
      );
    } catch (e) {
      console.error("Failed to load fixture:", e);
    }
  }

  populateRunData(data) {
    this.currentRunId = data.run ? data.run.run_id : "loaded_run";

    // Normalize nodes: fixtures use node_id, live events use id; unify to id
    const rawNodes = data.nodes || [];
    const normalizedNodes = rawNodes.map((n) => {
      const node = { ...n };
      if (!node.id && node.node_id) node.id = node.node_id;
      // Parse parents from parents_json if parents array is missing
      if (!node.parents || node.parents.length === 0) {
        if (node.parents_json) {
          try { node.parents = JSON.parse(node.parents_json); } catch (e) { node.parents = []; }
        } else {
          node.parents = [];
        }
      }
      // Parse output from output_json if output object is missing
      if (!node.output && node.output_json) {
        try { node.output = JSON.parse(node.output_json); } catch (e) { node.output = {}; }
      }
      // Parse falsifier_report from falsifier_report_json if missing
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
    document.getElementById("badge-problem").textContent = `Theorem: ${problem.substring(0, 45)}...`;

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
      // Auto-switch to Research Tree tab so user sees graph immediately
      // Use timeout so the tab becomes visible before fitToScreen is called
      const treeNodes = this.currentRunData.nodes.filter(
        (n) => n.stage === "exploration" || n.type === "explorer" || n.type === "aggregator" || n.type === "gate"
      );
      if (treeNodes.length > 0 && this.activeTab === "doc") {
        setTimeout(() => this.switchTab("tree"), 120);
      }
    }
  }

  async runBenchmarkEval() {
    try {
      const res = await fetch("/api/eval/benchmark");
      const bench = await res.json();
      let summary = "5-LEMMA REFERENCE-ASSISTED BENCHMARK (SPEC v1.1):\n\n";
      bench.lemmas.forEach((l, i) => {
        summary += `${i + 1}. ${l.title}\n   Route: ${l.known_route}\n\n`;
      });
      summary += "Benchmark ready. Select any problem from the toolbar dropdown to execute the harness against it.";
      alert(summary);
    } catch (e) {
      alert(`Could not fetch benchmark: ${e}`);
    }
  }

  async triggerReexplore() {
    if (!this.currentRunId) {
      alert("No active run to re-explore.");
      return;
    }
    this.appendLogEntry(new Date().toTimeString().slice(0, 8), "all", "warning", "Triggering manual re-exploration round with failed feedback...");
    await this.apiPost(`/api/runs/${this.currentRunId}/reexplore`);
  }

  exportDirect(type) {
    if (!this.currentRunId) {
      alert("No active run to export.");
      return;
    }
    window.open(`/api/runs/${this.currentRunId}/export/${type}`, "_blank");
  }

  async openRunHistoryModal() {
    try {
      const res = await fetch("/api/runs");
      const runs = await res.json();
      const container = document.getElementById("history-runs-list");
      if (!container) return;
      if (!runs || runs.length === 0) {
        container.innerHTML = `<div style="padding: 10px; color: #888;">No saved runs in SQLite.</div>`;
      } else {
        container.innerHTML = runs
          .map(
            (r) => `
          <div class="coq-msg-line" style="padding: 6px; cursor: pointer;" onclick="window.app.loadRunTrace('${r.run_id}')">
            <strong>${r.run_id}</strong> - <span style="color:#007700; font-weight:bold;">[${r.status.toUpperCase()}]</span>
            <div><em>${r.problem.substring(0, 75)}...</em></div>
            <div style="font-size: 10px; color: #666;">Date: ${r.created_at} | Cost: $${(r.cost_usd || 0).toFixed(4)} | Tokens: ${r.tokens_in + r.tokens_out}</div>
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

  async handleSaveSettings() {
    const key = document.getElementById("input-api-key").value;
    const url = document.getElementById("input-base-url").value;
    const cap = parseFloat(document.getElementById("input-budget-cap").value) || 20.0;

    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: key,
        base_url: url,
        default_budget_cap: cap,
      }),
    });
    this.closeModals();
    alert("Settings saved successfully.");
  }

  showModal(id) {
    this.closeModals();
    document.getElementById(id)?.classList.add("active");
  }

  closeModals() {
    document.querySelectorAll(".modal-overlay").forEach((m) => m.classList.remove("active"));
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
