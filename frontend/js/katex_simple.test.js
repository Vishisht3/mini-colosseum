// Script renderer tests: real math must be visible, no fabricated proof text.
global.window = global;
require("./katex_simple.js");
const R = global.SimpleLaTeXRenderer;

function assert(cond, msg) {
  if (!cond) throw new Error(`Assertion failed: ${msg}`);
}

// Empty state must not invent a theorem
const empty = R.renderDocument("", [], []);
assert(!empty.includes("mini_colosseum_spec"), "empty script must not contain a fabricated theorem");
assert(empty.includes("No proof script yet"), "empty script explains how to get a proof");

// Section titles and math are rendered readably
const doc = R.renderDocument(
  "\\documentclass{article}\n\\usepackage{amsmath}\n\\begin{document}\n\\section{Counting edges}\nWe have $\\sum_{i=1}^n i = \\frac{n(n+1)}{2}$ and \\[ x_i \\le n^2. \\]\n\\end{document}",
  [],
  []
);
assert(doc.includes("Section 1: Counting edges"), "section title is visible");
assert(doc.includes("∑"), "sum symbol is rendered");
assert(!doc.includes("\\documentclass"), "preamble is hidden");

// Per-node fallback: solver bodies are visible without an assembled document
const fromNodes = R.renderDocument("", [
  { id: "SEC_1", label: "SEC_1", status: "accepted", output: { section_index: 1, title: "Setup", claimed_result: "Pairs are distinct", solution_body: "Let $a_i$ be the longest chain ending at $x_i$." } },
], []);
assert(fromNodes.includes("Pairs are distinct"), "node claim is visible");
assert(fromNodes.includes("longest chain"), "node proof body math is visible");

// Raw statement text (no $ delimiters) renders readably too — maths and CS
const readable = R.toReadable("Show x^2 + y_i \\le \\sum_{i=1}^n a_i for O(n log n) steps");
assert(readable.includes("<sup>2</sup>"), "superscript is rendered");
assert(readable.includes("<sub>i</sub>"), "subscript is rendered");
assert(readable.includes("∑"), "sum symbol is rendered");
assert(readable.includes("≤"), "inequality is rendered");
assert(readable.includes("O(n log n)"), "CS notation stays readable");

console.log("KaTeX renderer tests passed.");
