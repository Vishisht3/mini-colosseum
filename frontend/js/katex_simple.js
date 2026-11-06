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

function sanitizeRawLatexString(raw) {
  if (!raw || typeof raw !== "string") return "";
  let s = raw.trim();

  // Unwrap raw or truncated JSON wrapper if present (e.g. {"status": "solved", "solution_body": "..."})
  if (s.startsWith("{") && (s.includes('"solution_body"') || s.includes('"latex_body"') || s.includes('"status"'))) {
    try {
      const parsed = JSON.parse(s);
      if (parsed && typeof parsed === "object") {
        s = String(parsed.solution_body || parsed.latex_body || parsed.proof_body || parsed.proof || parsed.revised_latex || s);
      }
    } catch (_) {
      const m = s.match(/"(?:solution_body|latex_body|proof_body|proof|revised_latex)"\s*:\s*"([\s\S]*)/);
      if (m) {
        let body = m[1];
        body = body.replace(/"\s*(?:,\s*"[a-zA-Z_]+"\s*:[\s\S]*|\}\s*)$/, "");
        s = body;
      }
    }
  }

  // Unescape double-escaped JSON sequences if present
  s = s.replace(/\\+u220[eE]/g, "∎");
  s = s.replace(/âˆŽ/g, "∎");
  s = s.replace(/\\n(?![a-zA-Z])/g, "\n");
  s = s.replace(/\\\\(?=[A-Za-z]+|[\{\}\(\)\[\],;!\|])/g, "\\");

  // Common LaTeX accents in author/theorem names
  s = s.replace(/\\H\{o\}/g, "ő").replace(/\\H\{u\}/g, "ű");
  s = s.replace(/\\'a/g, "á").replace(/\\'e/g, "é").replace(/\\'i/g, "í").replace(/\\'o/g, "ó").replace(/\\'u/g, "ú");
  s = s.replace(/\\'\{a\}/g, "á").replace(/\\'\{e\}/g, "é").replace(/\\'\{o\}/g, "ó");

  return s;
}

const MATH_SYMBOL_REPLACEMENTS = [
  [/\\alpha(?![a-zA-Z])/g, "α"],
  [/\\beta(?![a-zA-Z])/g, "β"],
  [/\\gamma(?![a-zA-Z])/g, "γ"],
  [/\\delta(?![a-zA-Z])/g, "δ"],
  [/\\varepsilon(?![a-zA-Z])/g, "ε"],
  [/\\epsilon(?![a-zA-Z])/g, "ε"],
  [/\\zeta(?![a-zA-Z])/g, "ζ"],
  [/\\eta(?![a-zA-Z])/g, "η"],
  [/\\vartheta(?![a-zA-Z])/g, "ϑ"],
  [/\\theta(?![a-zA-Z])/g, "θ"],
  [/\\iota(?![a-zA-Z])/g, "ι"],
  [/\\kappa(?![a-zA-Z])/g, "κ"],
  [/\\lambda(?![a-zA-Z])/g, "λ"],
  [/\\mu(?![a-zA-Z])/g, "μ"],
  [/\\nu(?![a-zA-Z])/g, "ν"],
  [/\\xi(?![a-zA-Z])/g, "ξ"],
  [/\\pi(?![a-zA-Z])/g, "π"],
  [/\\rho(?![a-zA-Z])/g, "ρ"],
  [/\\sigma(?![a-zA-Z])/g, "σ"],
  [/\\tau(?![a-zA-Z])/g, "τ"],
  [/\\upsilon(?![a-zA-Z])/g, "υ"],
  [/\\varphi(?![a-zA-Z])/g, "φ"],
  [/\\phi(?![a-zA-Z])/g, "ϕ"],
  [/\\chi(?![a-zA-Z])/g, "χ"],
  [/\\psi(?![a-zA-Z])/g, "ψ"],
  [/\\omega(?![a-zA-Z])/g, "ω"],
  [/\\Gamma(?![a-zA-Z])/g, "Γ"],
  [/\\Delta(?![a-zA-Z])/g, "Δ"],
  [/\\Theta(?![a-zA-Z])/g, "Θ"],
  [/\\Lambda(?![a-zA-Z])/g, "Λ"],
  [/\\Xi(?![a-zA-Z])/g, "Ξ"],
  [/\\Pi(?![a-zA-Z])/g, "Π"],
  [/\\Sigma(?![a-zA-Z])/g, "Σ"],
  [/\\Phi(?![a-zA-Z])/g, "Φ"],
  [/\\Psi(?![a-zA-Z])/g, "Ψ"],
  [/\\Omega(?![a-zA-Z])/g, "Ω"],
  [/\\sum(?![a-zA-Z])/g, "∑"],
  [/\\prod(?![a-zA-Z])/g, "∏"],
  [/\\bigcup(?![a-zA-Z])/g, "⋃"],
  [/\\bigcap(?![a-zA-Z])/g, "⋂"],
  [/\\int(?![a-zA-Z])/g, "∫"],
  [/\\infty(?![a-zA-Z])/g, "∞"],
  [/\\partial(?![a-zA-Z])/g, "∂"],
  [/\\nabla(?![a-zA-Z])/g, "∇"],
  [/\\leq(?![a-zA-Z])/g, "≤"],
  [/\\le(?![a-zA-Z])/g, "≤"],
  [/\\geq(?![a-zA-Z])/g, "≥"],
  [/\\ge(?![a-zA-Z])/g, "≥"],
  [/\\neq(?![a-zA-Z])/g, "≠"],
  [/\\ne(?![a-zA-Z])/g, "≠"],
  [/\\approx(?![a-zA-Z])/g, "≈"],
  [/\\equiv(?![a-zA-Z])/g, "≡"],
  [/\\cong(?![a-zA-Z])/g, "≅"],
  [/\\simeq(?![a-zA-Z])/g, "≃"],
  [/\\sim(?![a-zA-Z])/g, "∼"],
  [/\\propto(?![a-zA-Z])/g, "∝"],
  [/\\ll(?![a-zA-Z])/g, "≪"],
  [/\\gg(?![a-zA-Z])/g, "≫"],
  [/\\pm(?![a-zA-Z])/g, "±"],
  [/\\mp(?![a-zA-Z])/g, "∓"],
  [/\\notin(?![a-zA-Z])/g, "∉"],
  [/\\in(?![a-zA-Z])/g, "∈"],
  [/\\ni(?![a-zA-Z])/g, "∋"],
  [/\\subsetneq(?![a-zA-Z])/g, "⊊"],
  [/\\subseteq(?![a-zA-Z])/g, "⊆"],
  [/\\subset(?![a-zA-Z])/g, "⊂"],
  [/\\supseteq(?![a-zA-Z])/g, "⊇"],
  [/\\supset(?![a-zA-Z])/g, "⊃"],
  [/\\sqcup(?![a-zA-Z])/g, "⊔"],
  [/\\sqcap(?![a-zA-Z])/g, "⊓"],
  [/\\cup(?![a-zA-Z])/g, "∪"],
  [/\\cap(?![a-zA-Z])/g, "∩"],
  [/\\emptyset(?![a-zA-Z])/g, "∅"],
  [/\\varnothing(?![a-zA-Z])/g, "∅"],
  [/\\forall(?![a-zA-Z])/g, "∀"],
  [/\\exists(?![a-zA-Z])/g, "∃"],
  [/\\times(?![a-zA-Z])/g, "×"],
  [/\\cdot(?![a-zA-Z])/g, "·"],
  [/\\oplus(?![a-zA-Z])/g, "⊕"],
  [/\\otimes(?![a-zA-Z])/g, "⊗"],
  [/\\perp(?![a-zA-Z])/g, "⊥"],
  [/\\parallel(?![a-zA-Z])/g, "∥"],
  [/\\nmid(?![a-zA-Z])/g, "∤"],
  [/\\mid(?![a-zA-Z])/g, "∣"],
  [/\\cdots(?![a-zA-Z])/g, "⋯"],
  [/\\ldots(?![a-zA-Z])/g, "…"],
  [/\\dots(?![a-zA-Z])/g, "…"],
  [/\\mapsto(?![a-zA-Z])/g, "↦"],
  [/\\rightarrow(?![a-zA-Z])/g, "→"],
  [/\\leftarrow(?![a-zA-Z])/g, "←"],
  [/\\leftrightarrow(?![a-zA-Z])/g, "↔"],
  [/\\to(?![a-zA-Z])/g, "→"],
  [/\\Rightarrow(?![a-zA-Z])/g, "⇒"],
  [/\\Leftarrow(?![a-zA-Z])/g, "⇐"],
  [/\\Leftrightarrow(?![a-zA-Z])/g, "⇔"],
  [/\\implies(?![a-zA-Z])/g, "⇒"],
  [/\\iff(?![a-zA-Z])/g, "⇔"],
  [/\\lfloor(?![a-zA-Z])/g, "⌊"],
  [/\\rfloor(?![a-zA-Z])/g, "⌋"],
  [/\\lceil(?![a-zA-Z])/g, "⌈"],
  [/\\rceil(?![a-zA-Z])/g, "⌉"],
  [/\\langle(?![a-zA-Z])/g, "⟨"],
  [/\\rangle(?![a-zA-Z])/g, "⟩"],
  [/\\blacksquare(?![a-zA-Z])/g, "∎"],
  [/\\Box(?![a-zA-Z])/g, "□"],
  [/\\square(?![a-zA-Z])/g, "□"],
  [/\\qedhere(?![a-zA-Z])/g, "∎"],
  [/\\qed(?![a-zA-Z])/g, "∎"],
  [/\\mathbb\{R\}/g, "ℝ"],
  [/\\mathbb\{N\}/g, "ℕ"],
  [/\\mathbb\{Z\}/g, "ℤ"],
  [/\\mathbb\{Q\}/g, "ℚ"],
  [/\\mathbb\{C\}/g, "ℂ"],
  [/\\mathbb\{E\}/g, "𝔼"],
  [/\\mathbb\{P\}/g, "ℙ"],
  [/\\mathbb\{F\}_2/g, "𝔽₂"],
  [/\\mathbb\{F\}/g, "𝔽"],
  [/\\mathbf\{R\}/g, "ℝ"],
  [/\\mathbf\{Z\}/g, "ℤ"],
  [/\\mathbf\{N\}/g, "ℕ"],
  [/\\bf\s+R\b/g, "ℝ"],
  [/\\bf\s+Z\b/g, "ℤ"],
  [/\\R(?![a-zA-Z])/g, "ℝ"],
  [/\\Z(?![a-zA-Z])/g, "ℤ"],
  [/\\C(?![a-zA-Z])/g, "𝒞"],
  [/\\crnum(?![a-zA-Z])/g, "cr"],
  [/\\log(?![a-zA-Z])/g, "log "],
  [/\\ln(?![a-zA-Z])/g, "ln "],
  [/\\exp(?![a-zA-Z])/g, "exp"],
  [/\\max(?![a-zA-Z])/g, "max"],
  [/\\min(?![a-zA-Z])/g, "min"],
  [/\\sup(?![a-zA-Z])/g, "sup"],
  [/\\inf(?![a-zA-Z])/g, "inf"],
  [/\\lim(?![a-zA-Z])/g, "lim"],
  [/\\sin(?![a-zA-Z])/g, "sin"],
  [/\\cos(?![a-zA-Z])/g, "cos"],
  [/\\tan(?![a-zA-Z])/g, "tan"],
  [/\\det(?![a-zA-Z])/g, "det"],
  [/\\gcd(?![a-zA-Z])/g, "gcd"],
  [/\\deg(?![a-zA-Z])/g, "deg"],
  [/\\dim(?![a-zA-Z])/g, "dim"],
  [/\\bmod(?![a-zA-Z])/g, " mod "],
  [/\\pmod\{([^{}]*)\}/g, " (mod $1)"],
  [/\\quad(?![a-zA-Z])/g, " "],
  [/\\qquad(?![a-zA-Z])/g, "  "],
];

class SimpleLaTeXRenderer {
  static renderMath(latex) {
    if (typeof window !== "undefined" && window.katex) {
      try {
        return window.katex.renderToString(latex, { throwOnError: false, displayMode: false });
      } catch (e) {
        // Fall through to the Unicode conversion below.
      }
    }

    let s = String(latex).trim();
    s = s.replace(/\\(?:left|right|big|Big|bigg|Bigg|bigl|bigr|Bigl|Bigr)\b/g, "");
    s = s.replace(/\\(?:text|mathrm|operatorname|mathcal|mathbf|textit|textbf|emph)\{([^{}]*)\}/g, "$1");
    s = s.replace(/\{\\(?:rm|bf|it|cal)\s+([^{}]*)\}/g, "$1");
    s = s.replace(/\\(?:rm|cal)\s+/g, "");
    s = s.replace(/\\overline\{([^{}]*)\}/g, "$1̄");
    s = s.replace(/\\mathring\{([^{}]*)\}/g, "$1°");
    s = s.replace(/\\mathring\s+([A-Za-z])/g, "$1°");

    MATH_SYMBOL_REPLACEMENTS.forEach(([rgx, rep]) => {
      s = s.replace(rgx, rep);
    });

    s = s.replace(/\\sqrt\{([^{}]+)\}/g, "√($1)");
    for (let pass = 0; pass < 2; pass++) {
      s = s.replace(/\\(?:t|d)?frac\{([^{}]+)\}\{([^{}]+)\}/g, "($1 / $2)");
    }
    s = s.replace(/\\binom\{([^{}]+)\}\{([^{}]+)\}/g, "C($1, $2)");
    s = s.replace(/\^\{([^{}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z+\-'])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^{}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z+\-])/g, "<sub>$1</sub>");
    s = s.replace(/\\\{/g, "{").replace(/\\\}/g, "}");
    s = s.replace(/\\[,;:!]/g, " ");
    s = s.replace(/\\tag\{([^{}]*)\}/g, " ($1)");

    return `<span class="math-tex" style="font-style: italic;">${s}</span>`;
  }

  static nodeBody(node) {
    const out = (node && node.output) || {};
    const raw =
      out.solution_body ||
      out.latex_body ||
      out.proof_body ||
      out.proof ||
      out.body ||
      out.raw ||
      "";
    return sanitizeRawLatexString(String(raw));
  }

  static nodeTitle(node, fallbackIdx) {
    const out = (node && node.output) || {};
    return sanitizeRawLatexString(String(out.title || node.label || `Section ${fallbackIdx}`));
  }

  static sectionIndexOf(node, position) {
    const out = (node && node.output) || {};
    if (out.section_index) return Number(out.section_index);
    const match = String((node && node.id) || "").match(/(\d+)/);
    return match ? Number(match[1]) : position;
  }

  static renderDocument(latexContent, sectionNodes = [], globalDefects = []) {
    let latex = sanitizeRawLatexString(latexContent || "");

    // No assembled document yet: build the script from per-section solver
    // bodies so the mathematician can read each node's actual math.
    if (!latex.trim() && sectionNodes.length > 0) {
      const parts = [];
      sectionNodes.forEach((node, i) => {
        const idx = SimpleLaTeXRenderer.sectionIndexOf(node, i + 1);
        const title = SimpleLaTeXRenderer.nodeTitle(node, idx);
        const out = node.output || {};
        const claim = sanitizeRawLatexString(String(out.claimed_result || out.target_claim || ""));
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

    // Collapse multi-line \[ ... \] and $$ ... $$ blocks onto single lines before line splitting
    // so display math blocks that span multiple lines never leak raw \[ or \] tokens.
    const collapseMultilineMath = (str) =>
      str
        .replace(/\\\[([\s\S]*?)\\\]/g, (_, inner) => `\\[ ${inner.replace(/\s*\n\s*/g, " ").trim()} \\]`)
        .replace(/\$\$([\s\S]*?)\$\$/g, (_, inner) => `$$ ${inner.replace(/\s*\n\s*/g, " ").trim()} $$`);

    latex = collapseMultilineMath(latex);

    const lines = latex.split("\n");
    let html = "";
    let currentSecIdx = 0;

    const renderLines = (textLines, processed) => {
      textLines.forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("%") && !/^%% SECTION_BODY_\d+ %%$/.test(trimmed)) {
          if (!trimmed) {
            html += `<div class="coq-line">&nbsp;</div>`;
          }
          return;
        }
        // Skip LaTeX preamble / document scaffolding / list wrappers.
        if (
          /^\\(documentclass|usepackage|newtheorem|theoremstyle|newcommand|renewcommand|DeclareMathOperator|author|date|begin\{document\}|end\{document\}|maketitle|begin\{abstract\}|end\{abstract\}|begin\{itemize\}|end\{itemize\}|begin\{enumerate\}|end\{enumerate\})/.test(
            trimmed
          )
        ) {
          return;
        }
        const titleMatch = trimmed.match(/^\\title\{(.+)\}\s*$/);
        if (titleMatch) {
          html += `<div class="coq-line declaration" style="font-weight:bold; font-size:14px;">${SimpleLaTeXRenderer.formatText(titleMatch[1])}</div>`;
          return;
        }
        const secMatch = trimmed.match(/^\\section\*?\{(.+)\}\s*$/);
        if (secMatch) {
          currentSecIdx++;
          html += `<div class="coq-line declaration document-section ${processed ? "processed" : ""}" data-section-idx="${currentSecIdx}" style="margin-top: 10px; font-weight:bold;">Section ${currentSecIdx}: ${SimpleLaTeXRenderer.formatText(secMatch[1])}</div>`;
          return;
        }
        const subMatch = trimmed.match(/^\\subsection\*?\{(.+)\}\s*$/);
        if (subMatch) {
          html += `<div class="coq-line ${processed ? "processed" : ""}" style="font-weight:bold;">${SimpleLaTeXRenderer.formatText(subMatch[1])}</div>`;
          return;
        }
        const bodyMatch = trimmed.match(/^%% SECTION_BODY_(\d+) %%$/);
        if (bodyMatch) {
          const idx = Number(bodyMatch[1]);
          const secNode = sectionNodes.find((n, i) => SimpleLaTeXRenderer.sectionIndexOf(n, i + 1) === idx);
          const body = secNode ? collapseMultilineMath(SimpleLaTeXRenderer.nodeBody(secNode)) : "";
          if (body) {
            renderLines(body.split("\n"), secNode.status === "accepted");
          } else {
            html += `<div class="coq-line" style="color:#777770; font-style:italic;">&nbsp;&nbsp;(Section ${idx} body pending solver execution...)</div>`;
          }
          return;
        }
        const beginEnvMatch = trimmed.match(/^\\begin\{(theorem|lemma|proposition|corollary|definition|claim|remark|proof)\}(?:\[([^\]]*)\])?(.*)$/i);
        if (beginEnvMatch) {
          const envName = beginEnvMatch[1];
          const optLabel = beginEnvMatch[2];
          const restText = (beginEnvMatch[3] || "").trim();
          const cap = envName.charAt(0).toUpperCase() + envName.slice(1).toLowerCase();
          const header = optLabel ? `${cap} (${SimpleLaTeXRenderer.formatText(optLabel)}).` : `${cap}.`;
          html += `<div class="coq-line ${processed ? "processed" : ""}"><strong>${header}</strong>${restText ? " " + SimpleLaTeXRenderer.formatText(restText) : ""}</div>`;
          return;
        }
        if (/^\\end\{proof\}/i.test(trimmed)) {
          html += `<div class="coq-line ${processed ? "processed" : ""}" style="text-align:right;">∎</div>`;
          return;
        }
        if (/^\\end\{(theorem|lemma|proposition|corollary|definition|claim|remark)\}/i.test(trimmed)) {
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
    let s = escapeHTMLText(sanitizeRawLatexString(String(text)));
    s = s.replace(/\$\$([\s\S]*?)\$\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\(([\s\S]*?)\\\)/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    MATH_SYMBOL_REPLACEMENTS.forEach(([rgx, rep]) => {
      s = s.replace(rgx, rep);
    });
    for (let pass = 0; pass < 2; pass++) {
      s = s.replace(/\\(?:t|d)?frac\{([^{}]+)\}\{([^{}]+)\}/g, "($1 / $2)");
    }
    s = s.replace(/\\binom\{([^{}]+)\}\{([^{}]+)\}/g, "C($1, $2)");
    s = s.replace(/\\sqrt\{([^{}]+)\}/g, "√($1)");
    s = s.replace(/\\(?:text|mathrm|mathbf|mathcal|textbf|textit|emph)\{([^{}]+)\}/g, "$1");
    s = s.replace(/\^\{([^{}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^{}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");
    s = s.replace(/&lt;=/g, "≤").replace(/&gt;=/g, "≥");
    s = s.replace(/\\([a-zA-Z]+)/g, "$1");
    return s;
  }

  static formatText(text) {
    if (!text) return "";
    let s = escapeHTMLText(sanitizeRawLatexString(String(text)));
    // Handle \item bullets
    s = s.replace(/^\s*\\item(?:\s*\[([^\]]*)\])?\s*/, (_, label) => (label ? `• <strong>${label}</strong> ` : "• "));
    s = s.replace(/\$\$([\s\S]*?)\$\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\[([\s\S]*?)\\\]/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\\(([\s\S]*?)\\\)/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\textbf\{([^{}]+)\}/g, "<strong>$1</strong>");
    s = s.replace(/\\textit\{([^{}]+)\}/g, "<em>$1</em>");
    s = s.replace(/\\emph\{([^{}]+)\}/g, "<em>$1</em>");
    s = s.replace(/\\paragraph\*?\{([^{}]+)\}/g, "<strong>$1</strong> ");
    s = s.replace(/\\(?:ref|eqref)\{([^{}]+)\}/g, "($1)");
    s = s.replace(/\\label\{[^{}]*\}/g, "");
    s = s.replace(/\\(?:par|smallskip|medskip|bigskip|noindent|hfill)\b/g, " ");
    s = s.replace(/\\(?:qed|qedhere|blacksquare|Box|square)\b/g, "∎");
    s = s.replace(/--/g, "–");
    return s;
  }
}

if (typeof window !== "undefined") {
  window.SimpleLaTeXRenderer = SimpleLaTeXRenderer;
  window.MathRenderer = SimpleLaTeXRenderer;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = SimpleLaTeXRenderer;
}
