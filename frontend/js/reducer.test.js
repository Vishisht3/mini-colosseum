const assert = require("assert");
const { reduceReplayEvents } = require("./reducer.js");

const events = [
  { event_type: "node_created", payload: { node: { id: "n1", status: "pending" } } },
  { event_type: "edge_added", payload: { edge: { source: "n1", target: "n2" } } },
  { event_type: "node_updated", payload: { node_id: "n1", updates: { status: "done" } } },
  { event_type: "knowledge_entry_added", payload: { entry: { title: "Invariant" } } },
];

const reduced = reduceReplayEvents(events);
assert.deepStrictEqual(reduced.nodes, [{ id: "n1", status: "done" }]);
assert.deepStrictEqual(reduced.edges, [{ source: "n1", target: "n2" }]);
assert.deepStrictEqual(reduced.knowledge_directory, [{ title: "Invariant" }]);
assert.notStrictEqual(reduced.events, events);
assert.strictEqual(events[0].payload.node.status, "pending");
console.log("Reducer tests passed.");
