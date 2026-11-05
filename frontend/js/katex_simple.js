/**
 * Mini-Colosseum Script & LaTeX Formatter.
 * Renders the actual assembled LaTeX (and per-section solver bodies) as
 * readable math text: section titles, claims, and proof bodies with
 * $...$, $$...$$, \(...\) and \[...\] segments converted to Unicode math.
 */

function escapeHTMLText(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

class SimpleLaTeXRenderer {
  static renderMath(latex) {
    if (window.katex) {
      try {
        return window.katex.renderToString(latex, { throwOnError: false, displayMode: false });
      } catch (e) {
        // Fall through to the Unicode conversion below.
      }
    }

    let s = String(latex).trim();
    s = s.replace(/\\left/g, "").replace(/\\right/g, "");
    s = s.replace(/\\text\{([^}]*)\}/g, "$1");
    s = s.replace(/\\mathrm\{([^}]*)\}/g, "$1");
    s = s.replace(/\\mathbf\{([^}]*)\}/g, "$1");
    const replacements = [
      [/\\alpha/g, "α"],
      [/\\beta/g, "β"],
      [/\\gamma/g, "γ"],
      [/\\delta/g, "δ"],
      [/\\epsilon/g, "ε"],
      [/\\sum/g, "∑"],
      [/\\prod/g, "∏"],
      [/\\int/g, "∫"],
      [/\\infty/g, "∞"],
      [/\\le/g, "≤"],
      [/\\ge/g, "≥"],
      [/\\neq/g, "≠"],
      [/\\in/g, "∈"],
      [/\\notin/g, "∉"],
      [/\\subset/g, "⊂"],
      [/\\subseteq/g, "⊆"],
      [/\\forall/g, "∀"],
      [/\\exists/g, "∃"],
      [/\\times/g, "×"],
      [/\\cdot/g, "·"],
      [/\\dots/g, "…"],
      [/\\ldots/g, "…"],
      [/\\mapsto/g, "↦"],
      [/\\to/g, "→"],
      [/\\Rightarrow/g, "⇒"],
      [/\\implies/g, "⇒"],
      [/\\iff/g, "⇔"],
      [/\\mathbb\{R\}/g, "ℝ"],
      [/\\mathbb\{N\}/g, "ℕ"],
      [/\\mathbb\{Z\}/g, "ℤ"],
      [/\\mathbb\{F\}_2/g, "𝔽₂"],
    ];
    replacements.forEach(([rgx, rep]) => {
      s = s.replace(rgx, rep);
    });

    s = s.replace(/\\sqrt\{([^}]+)\}/g, "√($1)");
    s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)");
    s = s.replace(/\\binom\{([^}]+)\}\{([^}]+)\}/g, "C($1, $2)");
    s = s.replace(/\^\{([^}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");
    s = s.replace(/\\\{/g, "{").replace(/\\\}/g, "}");
    s = s.replace(/\\,/g, " ");

    return `<span class="math-tex" style="font-style: italic;">${s}</span>`;
  }

  static nodeBody(node) {
    const out = (node && node.output) || {};
    return out.solution_body || out.latex_body || out.body || "";
  }

  static nodeTitle(node, fallbackIdx) {
    const out = (node && node.output) || {};
    return out.title || node.label || `Section ${fallbackIdx}`;
  }

  static sectionIndexOf(node, position) {
    const out = (node && node.output) || {};
    if (out.section_index) return Number(out.section_index);
    const match = String((node && node.id) || "").match(/(\d+)/);
    return match ? Number(match[1]) : position;
  }

  static renderDocument(latexContent, sectionNodes = [], globalDefects = []) {
    let latex = latexContent || "";

    // No assembled document yet: build the script from per-section solver
    // bodies so the mathematician can read each node's actual math.
    if (!latex.trim() && sectionNodes.length > 0) {
      const parts = [];
      sectionNodes.forEach((node, i) => {
        const idx = SimpleLaTeXRenderer.sectionIndexOf(node, i + 1);
        const title = SimpleLaTeXRenderer.nodeTitle(node, idx);
        const out = node.output || {};
        const claim = out.claimed_result || out.target_claim || "";
        const body = SimpleLaTeXRenderer.nodeBody(node);
        parts.push(`\\section{${title}}`);
        if (claim) parts.push(`Claim: ${claim}`);
        if (body) parts.push(body);
        if (!claim && !body) parts.push(`(Section ${idx} has no proof body yet.)`);
      });
      latex = parts.join("\n");
    }

    if (!latex.trim()) {
      return `<div class="coq-line" style="color:#777777; font-style:italic;">No proof script yet. Run the proof engine, or open a saved run from History to replay it here.</div>`;
    }

    const lines = latex.split("\n");
    let html = "";
    let currentSecIdx = 0;

    const renderLines = (textLines, processed) => {
      textLines.forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed) {
          html += `<div class="coq-line">&nbsp;</div>`;
          return;
        }
        // Skip LaTeX preamble / document scaffolding.
        if (/^\\(documentclass|usepackage|newtheorem|newcommand|renewcommand|begin\{document\}|end\{document\}|maketitle|begin\{abstract\}|end\{abstract\})/.test(trimmed)) {
          return;
        }
        const titleMatch = trimmed.match(/^\\title\{([^}]+)\}/);
        if (titleMatch) {
          html += `<div class="coq-line declaration" style="font-weight:bold; font-size:14px;">${SimpleLaTeXRenderer.formatText(titleMatch[1])}</div>`;
          return;
        }
        const secMatch = trimmed.match(/^\\section\*?\{([^}]+)\}/);
        if (secMatch) {
          currentSecIdx++;
          html += `<div class="coq-line declaration ${processed ? "processed" : ""}" data-section-idx="${currentSecIdx}" style="margin-top: 10px; font-weight:bold;">Section ${currentSecIdx}: ${SimpleLaTeXRenderer.formatText(secMatch[1])}</div>`;
          return;
        }
        const subMatch = trimmed.match(/^\\subsection\*?\{([^}]+)\}/);
        if (subMatch) {
          html += `<div class="coq-line ${processed ? "processed" : ""}" style="font-weight:bold;">${SimpleLaTeXRenderer.formatText(subMatch[1])}</div>`;
          return;
        }
        const bodyMatch = trimmed.match(/^%% SECTION_BODY_(\d+) %%$/);
        if (bodyMatch) {
          const idx = Number(bodyMatch[1]);
          const secNode = sectionNodes.find((n, i) => SimpleLaTeXRenderer.sectionIndexOf(n, i + 1) === idx);
          const body = secNode ? SimpleLaTeXRenderer.nodeBody(secNode) : "";
          if (body) {
            renderLines(body.split("\n"), secNode.status === "accepted");
          } else {
            html += `<div class="coq-line" style="color:#777770; font-style:italic;">&nbsp;&nbsp;(Section ${idx} body pending solver execution...)</div>`;
          }
          return;
        }
        if (/^\\begin\{(theorem|lemma|proof|definition)\}/.test(trimmed) || /^\\end\{(theorem|lemma|proof|definition)\}/.test(trimmed)) {
          html += `<div class="coq-line ${processed ? "processed" : ""}" style="font-weight:bold;">${escapeHTMLText(trimmed.replace(/\\(begin|end)\{(\w+)\}/, "$2:"))}</div>`;
          return;
        }
        html += `<div class="coq-line ${processed ? "processed" : ""}">${SimpleLaTeXRenderer.formatText(line)}</div>`;
      });
    };

    // Sections are "processed" (accepted) when their solver node accepted.
    const anyAccepted = sectionNodes.some((n) => n.status === "accepted");
    renderLines(lines, anyAccepted);
    return html;
  }

  // Render a problem statement (maths or CS) readably: LaTeX commands,
  // superscripts/subscripts and symbols become plain readable text.
  static toReadable(text) {
    if (!text) return "";
    let s = escapeHTMLText(text);
    s = s.replace(/\$\$([^$]+)\$\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\(([\s\S]*?)\\\)/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    const symbols = [
      [/\\sum/g, "∑"], [/\\prod/g, "∏"], [/\\int/g, "∫"], [/\\infty/g, "∞"],
      [/\\alpha/g, "α"], [/\\beta/g, "β"], [/\\gamma/g, "γ"], [/\\delta/g, "δ"], [/\\epsilon/g, "ε"],
      [/\\forall/g, "∀"], [/\\exists/g, "∃"], [/\\in/g, "∈"], [/\\notin/g, "∉"],
      [/\\subseteq/g, "⊆"], [/\\subset/g, "⊂"], [/\\times/g, "×"], [/\\cdot/g, "·"],
      [/\\mapsto/g, "↦"], [/\\to/g, "→"], [/\\Rightarrow/g, "⇒"], [/\\iff/g, "⇔"],
      [/\\mathbb\{R\}/g, "ℝ"], [/\\mathbb\{N\}/g, "ℕ"], [/\\mathbb\{Z\}/g, "ℤ"],
      [/\\le(?![a-zA-Z])/g, "≤"], [/\\ge(?![a-zA-Z])/g, "≥"], [/\\neq/g, "≠"],
      [/\\ldots/g, "…"], [/\\dots/g, "…"],
    ];
    symbols.forEach(([rgx, rep]) => { s = s.replace(rgx, rep); });
    s = s.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, "($1 / $2)");
    s = s.replace(/\\sqrt\{([^{}]+)\}/g, "√($1)");
    s = s.replace(/\\text\{([^{}]+)\}/g, "$1");
    s = s.replace(/\^\{([^}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");
    s = s.replace(/&lt;=/g, "≤").replace(/&gt;=/g, "≥");
    s = s.replace(/\\([a-zA-Z]+)/g, "$1");
    return s;
  }

  static formatText(text) {
    if (!text) return "";
    let s = escapeHTMLText(text);
    s = s.replace(/\$\$([^$]+)\$\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\(([\s\S]*?)\\\)/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\textbf\{([^}]+)\}/g, "<strong>$1</strong>");
    s = s.replace(/\\textit\{([^}]+)\}/g, "<em>$1</em>");
    s = s.replace(/\\emph\{([^}]+)\}/g, "<em>$1</em>");
    return s;
  }
}

window.SimpleLaTeXRenderer = SimpleLaTeXRenderer;
