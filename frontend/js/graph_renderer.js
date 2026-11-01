/**
 * Mini-Colosseum High-Density SVG Graph Renderer
 * Implements Section 6.6 conventions:
 * - Rectangular nodes with short label and paired status glyph
 * - Small red-bordered falsifier attack tags attached to nodes
 * - Retry counter badge on section nodes
 * - Overlapping reuse edges highlighted
 * - Pan, zoom, fit-to-screen, click-to-select (not draggable)
 */

class GraphRenderer {
  constructor(containerElement, onNodeSelect) {
    this.container = containerElement;
    this.onNodeSelect = onNodeSelect;
    this.selectedNodeId = null;

    // Viewport transform
    this.scale = 1.0;
    this.translateX = 0;
    this.translateY = 0;
    this.isPanning = false;
    this.startX = 0;
    this.startY = 0;

    this.layoutEngine = new HierarchicalLayout({
      nodeWidth: 84,
      nodeHeight: 34,
      layerSpacing: 65,
      nodeSpacing: 28,
    });

    this.nodes = [];
    this.edges = [];
    this.initSVG();
  }

  initSVG() {
    this.container.innerHTML = `
      <svg class="graph-canvas" width="100%" height="100%">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#666660"/>
          </marker>
          <marker id="arrow-blue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#1a5fb4"/>
          </marker>
        </defs>
        <g id="viewport-group">
          <g id="edges-layer"></g>
          <g id="nodes-layer"></g>
        </g>
      </svg>
    `;

    this.svg = this.container.querySelector("svg");
    this.viewportGroup = this.container.querySelector("#viewport-group");
    this.edgesLayer = this.container.querySelector("#edges-layer");
    this.nodesLayer = this.container.querySelector("#nodes-layer");

    // Pan & zoom handlers
    this.svg.addEventListener("mousedown", (e) => {
      if (e.target.closest(".svg-node")) return;
      this.isPanning = true;
      this.startX = e.clientX - this.translateX;
      this.startY = e.clientY - this.translateY;
    });

    window.addEventListener("mousemove", (e) => {
      if (!this.isPanning) return;
      this.translateX = e.clientX - this.startX;
      this.translateY = e.clientY - this.startY;
      this.updateTransform();
    });

    window.addEventListener("mouseup", () => {
      this.isPanning = false;
    });

    this.svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newScale = Math.min(Math.max(this.scale * zoomFactor, 0.25), 3.0);
      
      const rect = this.svg.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      this.translateX = mouseX - (mouseX - this.translateX) * (newScale / this.scale);
      this.translateY = mouseY - (mouseY - this.translateY) * (newScale / this.scale);
      this.scale = newScale;
      this.updateTransform();
    });
  }

  updateTransform() {
    this.viewportGroup.setAttribute(
      "transform",
      `translate(${this.translateX}, ${this.translateY}) scale(${this.scale})`
    );
  }

  fitToScreen() {
    if (this.nodes.length === 0) return;
    const bbox = this.viewportGroup.getBBox();
    const rect = this.svg.getBoundingClientRect();
    if (bbox.width === 0 || bbox.height === 0) return;

    const scaleX = (rect.width - 60) / bbox.width;
    const scaleY = (rect.height - 60) / bbox.height;
    this.scale = Math.min(scaleX, scaleY, 1.2);
    this.translateX = (rect.width - bbox.width * this.scale) / 2 - bbox.x * this.scale;
    this.translateY = 30 - bbox.y * this.scale;
    this.updateTransform();
  }

  resetZoom() {
    this.scale = 1.0;
    this.translateX = 40;
    this.translateY = 40;
    this.updateTransform();
  }

  setData(nodes, edges, options = {}) {
    this.nodes = nodes || [];
    this.edges = edges || [];
    this.render(options);
  }

  setSelectedNode(nodeId) {
    this.selectedNodeId = nodeId;
    const allSvgNodes = this.nodesLayer.querySelectorAll(".svg-node");
    allSvgNodes.forEach((el) => {
      if (el.getAttribute("data-id") === nodeId) {
        el.classList.add("selected");
      } else {
        el.classList.remove("selected");
      }
    });
  }

  getStatusStyle(status) {
    switch (status) {
      case "running":
        return { bg: "#d0e4f7", border: "#2b78c5", text: "#0b3866", glyph: "~" };
      case "accepted":
        return { bg: "#d2edd9", border: "#2e8b57", text: "#0e4c27", glyph: "OK" };
      case "conditional":
        return { bg: "#fdf0cd", border: "#d4a017", text: "#664d03", glyph: "?" };
      case "rejected":
        return { bg: "#f9d8d6", border: "#cb3837", text: "#781716", glyph: "X" };
      case "error":
        return { bg: "#781716", border: "#4d0f0e", text: "#ffffff", glyph: "!" };
      case "pending":
      default:
        return { bg: "#ecece8", border: "#b8b8b0", text: "#444440", glyph: "-" };
    }
  }

  render(options = {}) {
    const layoutRes = this.layoutEngine.layout(this.nodes, this.edges, options);

    // Render Edges
    let edgesHtml = "";
    layoutRes.edges.forEach((e) => {
      const isOverlap = e.isOverlap;
      const marker = isOverlap ? "url(#arrow-blue)" : "url(#arrow)";
      const strokeClass = isOverlap ? "svg-edge overlap-edge" : "svg-edge";

      // Curved cubic bezier
      const dy = Math.abs(e.y2 - e.y1);
      const cp1y = e.y1 + dy * 0.45;
      const cp2y = e.y2 - dy * 0.45;
      const pathD = `M ${e.x1} ${e.y1} C ${e.x1} ${cp1y}, ${e.x2} ${cp2y}, ${e.x2} ${e.y2}`;

      edgesHtml += `<path class="${strokeClass}" d="${pathD}" marker-end="${marker}"/>`;
    });
    this.edgesLayer.innerHTML = edgesHtml;

    // Render Nodes
    let nodesHtml = "";
    layoutRes.nodes.forEach((n) => {
      if (n.isCollapsedGroup) {
        nodesHtml += `
          <g class="svg-node collapsed-group" data-id="${n.id}" transform="translate(${n.x - n.width / 2}, ${n.y - n.height / 2})">
            <rect width="${n.width}" height="${n.height}" fill="#eaeae5" stroke="#999990" stroke-dasharray="3,3" />
            <text x="12" y="18" font-size="11" fill="#444440" font-weight="bold">${n.label}</text>
          </g>
        `;
        return;
      }

      const style = this.getStatusStyle(n.status);
      const isSelected = n.id === this.selectedNodeId;
      const selectedClass = isSelected ? "selected" : "";

      // Top-left label and top-right glyph
      const label = n.label || n.id;
      const glyph = style.glyph;

      // Falsifier tag: small red-bordered tag on attacked node
      let falsifierTag = "";
      if (n.falsifier_report) {
        const fVerdict = n.falsifier_report.verdict || "survives";
        const tagText = fVerdict === "survives" ? "F:OK" : (fVerdict === "needs_repair" ? "F:repair" : "F:reject");
        const tagColor = fVerdict === "survives" ? "#2e8b57" : "#cb3837";
        falsifierTag = `
          <g transform="translate(46, -9)">
            <rect width="42" height="15" fill="#ffffff" stroke="${tagColor}" stroke-width="1.2"/>
            <text x="21" y="11" font-size="9" font-weight="bold" fill="${tagColor}" text-anchor="middle">${tagText}</text>
          </g>
        `;
      }

      // Retry count badge for DAG section nodes
      let retryBadge = "";
      if (n.retry_count && n.retry_count > 0) {
        retryBadge = `
          <g transform="translate(-4, -9)">
            <rect width="44" height="15" fill="#fdf0cd" stroke="#d4a017" stroke-width="1.2"/>
            <text x="22" y="11" font-size="9" font-weight="bold" fill="#664d03" text-anchor="middle">retry:${n.retry_count}</text>
          </g>
        `;
      }

      nodesHtml += `
        <g class="svg-node ${selectedClass}" data-id="${n.id}" transform="translate(${n.x - n.width / 2}, ${n.y - n.height / 2})">
          <rect class="node-box" width="${n.width}" height="${n.height}" fill="${style.bg}" stroke="${style.border}" />
          <text x="8" y="22" font-size="11" font-weight="bold" fill="${style.text}">${label}</text>
          <text x="${n.width - 8}" y="22" font-size="11" font-weight="bold" fill="${style.text}" text-anchor="end">${glyph}</text>
          ${falsifierTag}
          ${retryBadge}
        </g>
      `;
    });
    this.nodesLayer.innerHTML = nodesHtml;

    // Attach click handlers
    this.nodesLayer.querySelectorAll(".svg-node").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const nodeId = el.getAttribute("data-id");
        this.setSelectedNode(nodeId);
        if (this.onNodeSelect) {
          const rawNode = this.nodes.find((n) => n.id === nodeId || n.node_id === nodeId);
          this.onNodeSelect(rawNode);
        }
      });
    });
  }
}

window.GraphRenderer = GraphRenderer;
