/**
 * Mini-Colosseum Top-Down Hierarchical DAG Layout Engine
 * Computes layer assignment, horizontal ordering, and coordinate positioning
 * Supports multi-parent overlapping reuse edges and multi-round grouping.
 */

class HierarchicalLayout {
  constructor(options = {}) {
    this.nodeWidth = options.nodeWidth || 80;
    this.nodeHeight = options.nodeHeight || 36;
    this.layerSpacing = options.layerSpacing || 70;
    this.nodeSpacing = options.nodeSpacing || 25;
  }

  layout(nodes, edges, options = {}) {
    if (!nodes || nodes.length === 0) {
      return { nodes: [], edges: [], width: 0, height: 0 };
    }

    const nodeMap = new Map();
    // Support both n.id (live events) and n.node_id (fixture schema)
    nodes.forEach(n => {
      const key = n.id || n.node_id;
      nodeMap.set(key, { ...n, id: key, inDegree: 0, outDegree: 0, layer: 0 });
    });

    // Count in/out degrees
    edges.forEach(e => {
      const src = nodeMap.get(e.source);
      const tgt = nodeMap.get(e.target);
      if (src && tgt) {
        src.outDegree++;
        tgt.inDegree++;
      }
    });

    // Group nodes by round
    const rounds = new Map();
    nodes.forEach(n => {
      const r = n.round || 1;
      if (!rounds.has(r)) rounds.set(r, []);
      const key = n.id || n.node_id;
      rounds.get(r).push(nodeMap.get(key));
    });

    let currentY = 40;
    let maxWidth = 400;
    const positionedNodes = [];
    const sortedRoundNumbers = Array.from(rounds.keys()).sort((a, b) => a - b);

    for (const rNum of sortedRoundNumbers) {
      const roundNodes = rounds.get(rNum);
      const isPriorRound = options.collapsePriorRounds && rNum < Math.max(...sortedRoundNumbers);

      if (isPriorRound) {
        // Collapsed group summary box for earlier round
        const collapsedId = `ROUND_${rNum}_COLLAPSED`;
        const collapsedNode = {
          id: collapsedId,
          isCollapsedGroup: true,
          round: rNum,
          label: `Round ${rNum} (Collapsed - ${roundNodes.length} nodes)`,
          status: "accepted",
          x: 200,
          y: currentY,
          width: 280,
          height: 28,
        };
        positionedNodes.push(collapsedNode);
        currentY += 50;
        continue;
      }

      // Assign layer ranks using topological / level logic
      // In exploration tree: leaves (inDegree 0 / parents 0) are at top (layer 0).
      // Downstream aggregators have layer = max(parent.layer) + 1.
      const roundNodeMap = new Map();
      roundNodes.forEach(n => roundNodeMap.set(n.id, n));

      // Separate into layers
      const layers = [];
      const assigned = new Set();

      // Find initial layer (nodes with no parents in this round)
      let currentLayer = roundNodes.filter(n => !n.parents || n.parents.length === 0);
      if (currentLayer.length === 0) currentLayer = [roundNodes[0]];

      currentLayer.forEach(n => {
        n.layer = 0;
        assigned.add(n.id);
      });
      layers.push(currentLayer);

      let remaining = roundNodes.filter(n => !assigned.has(n.id));
      let safetyIter = 0;

      while (remaining.length > 0 && safetyIter < 20) {
        safetyIter++;
        // Find nodes whose parents are all assigned or whose layer can be derived
        const nextLayer = [];
        for (const n of remaining) {
          const parents = (n.parents || []).filter(pid => roundNodeMap.has(pid));
          const allParentsAssigned = parents.length === 0 || parents.every(pid => assigned.has(pid));
          if (allParentsAssigned) {
            const maxParentLayer = parents.length > 0
              ? Math.max(...parents.map(pid => roundNodeMap.get(pid).layer))
              : layers.length - 1;
            n.layer = maxParentLayer + 1;
            nextLayer.push(n);
          }
        }

        if (nextLayer.length === 0) {
          // Break cyclic / disconnected stalemate
          const fallback = remaining[0];
          fallback.layer = layers.length;
          nextLayer.push(fallback);
        }

        nextLayer.forEach(n => assigned.add(n.id));
        layers.push(nextLayer);
        remaining = roundNodes.filter(n => !assigned.has(n.id));
      }

      // Order nodes horizontally within each layer to minimize edge crossings
      // Calculate barycenter of parents
      for (let l = 1; l < layers.length; l++) {
        layers[l].sort((a, b) => {
          const aParents = (a.parents || []).map(pid => roundNodeMap.get(pid)).filter(Boolean);
          const bParents = (b.parents || []).map(pid => roundNodeMap.get(pid)).filter(Boolean);
          const aAvg = aParents.length > 0 ? aParents.reduce((acc, p) => acc + (p.x || 0), 0) / aParents.length : 0;
          const bAvg = bParents.length > 0 ? bParents.reduce((acc, p) => acc + (p.x || 0), 0) / bParents.length : 0;
          return aAvg - bAvg;
        });
      }

      // Position nodes in coordinates
      const maxLayerCount = Math.max(...layers.map(l => l.length), 1);
      const totalWidthForRound = maxLayerCount * (this.nodeWidth + this.nodeSpacing) + 60;
      if (totalWidthForRound > maxWidth) maxWidth = totalWidthForRound;

      layers.forEach((layer, layerIdx) => {
        const count = layer.length;
        const totalLayerWidth = count * this.nodeWidth + (count - 1) * this.nodeSpacing;
        const startX = Math.max(30, (totalWidthForRound - totalLayerWidth) / 2);

        layer.forEach((node, nodeIdx) => {
          node.x = startX + nodeIdx * (this.nodeWidth + this.nodeSpacing) + this.nodeWidth / 2;
          node.y = currentY + layerIdx * (this.nodeHeight + this.layerSpacing);
          node.width = this.nodeWidth;
          node.height = this.nodeHeight;
          positionedNodes.push(node);
        });
      });

      currentY += layers.length * (this.nodeHeight + this.layerSpacing) + 30;
    }

    // Edge routing
    const posMap = new Map();
    positionedNodes.forEach(n => posMap.set(n.id, n));

    const positionedEdges = [];
    edges.forEach(e => {
      const src = posMap.get(e.source);
      const tgt = posMap.get(e.target);
      if (src && tgt) {
        positionedEdges.push({
          source: e.source,
          target: e.target,
          type: e.edge_type || e.type || "aggregation",
          isOverlap: src.outDegree > 1,
          x1: src.x,
          y1: src.y + src.height / 2,
          x2: tgt.x,
          y2: tgt.y - tgt.height / 2,
        });
      }
    });

    return {
      nodes: positionedNodes,
      edges: positionedEdges,
      width: Math.max(maxWidth, 700),
      height: Math.max(currentY + 60, 500),
    };
  }
}

window.HierarchicalLayout = HierarchicalLayout;
