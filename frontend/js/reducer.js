/**
 * Pure event reducer used by offline replay.
 * The input event list is never mutated.
 */
function reduceReplayEvents(events) {
  const replayData = {
    nodes: [],
    edges: [],
    events: events.slice(),
    assembled_latex: "",
    knowledge_directory: [],
    hmed_records: [],
  };

  for (const evt of events) {
    const payload = evt.payload || evt;
    if (evt.event_type === "node_created" || payload.type === "node_created") {
      const node = payload.node || payload;
      if (node.id) replayData.nodes.push({ ...node });
    } else if (evt.event_type === "edge_added" || payload.type === "edge_added") {
      const edge = payload.edge || payload;
      if (edge.source && edge.target) replayData.edges.push({ ...edge });
    } else if (evt.event_type === "node_updated" || payload.type === "node_updated") {
      const nodeId = payload.node_id || (payload.node && payload.node.id);
      const existing = replayData.nodes.find((node) => node.id === nodeId);
      if (existing) Object.assign(existing, payload.node || payload.updates || {});
    } else if (evt.event_type === "knowledge_entry_added" || payload.type === "knowledge_entry_added") {
      if (payload.entry) replayData.knowledge_directory.push(payload.entry);
    }
  }

  return replayData;
}

if (typeof window !== "undefined") {
  window.reduceReplayEvents = reduceReplayEvents;
}
if (typeof module !== "undefined") {
  module.exports = { reduceReplayEvents };
}
