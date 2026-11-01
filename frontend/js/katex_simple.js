/**
 * Mini-Colosseum CoqIDE Script & LaTeX Formatter
 * Implements the authentic CoqIDE script view with lime-green evaluated regions,
 * syntax highlighting, and subgoals display matching the reference screenshot.
 */

class SimpleLaTeXRenderer {
  static renderMath(latex) {
    if (window.katex) {
      try {
        return window.katex.renderToString(latex, { throwOnError: false, displayMode: false });
      } catch (e) {
        // Fallback
      }
    }

    let s = latex.trim();
    const replacements = [
      [/\\alpha/g, "α"],
      [/\\beta/g, "β"],
      [/\\gamma/g, "γ"],
      [/\\delta/g, "δ"],
      [/\\epsilon/g, "ε"],
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
      [/\\mapsto/g, "↦"],
      [/\\to/g, "→"],
      [/\\Rightarrow/g, "⇒"],
      [/\\mathbb\{R\}/g, "ℝ"],
      [/\\mathbb\{N\}/g, "ℕ"],
      [/\\mathbb\{Z\}/g, "ℤ"],
      [/\\mathbb\{F\}_2/g, "𝔽₂"],
    ];

    replacements.forEach(([rgx, rep]) => {
      s = s.replace(rgx, rep);
    });

    s = s.replace(/\^\{([^}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");
    s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)");

    return `<span class="math-tex" style="font-style: italic;">${s}</span>`;
  }

  static renderDocument(latexContent, sectionNodes = [], globalDefects = []) {
    if (!latexContent) {
      return `
        <div class="coq-line declaration">Theorem mini_colosseum_spec : forall (statement : Prop), Proven statement.</div>
        <div class="coq-line keyword">Proof.</div>
        <div class="coq-line">  intro statement.</div>
        <div class="coq-line" style="color:#777777;">  (* Awaiting research orchestrator initialization... *)</div>
      `;
    }

    const lines = latexContent.split("\n");
    let html = "";
    let currentSecIdx = 0;
    let inEvaluatedRegion = true;

    // Convert LaTeX structure into Coq script with lime green evaluation background
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        html += `<div class="coq-line">&nbsp;</div>`;
        return;
      }

      // Check for section headings
      const secMatch = trimmed.match(/^\\section\{([^}]+)\}/);
      if (secMatch) {
        currentSecIdx++;
        const secNode = sectionNodes.find(
          (n) => n.id === `SEC_${currentSecIdx}` || n.label === `SEC_${currentSecIdx}`
        );
        inEvaluatedRegion = secNode ? secNode.status === "accepted" : false;

        const processedClass = inEvaluatedRegion ? "processed" : "";
        html += `
          <div class="coq-line declaration ${processedClass}" style="margin-top: 8px;">
            <span style="color:#cc4400; font-weight:bold;">Lemma</span> section_${currentSecIdx} : <span style="color:#0000cc; font-weight:bold;">forall</span> (ctx : Context), Subproblem_${currentSecIdx}.
          </div>
          <div class="coq-line keyword ${processedClass}">Proof. (* ${secMatch[1]} *)</div>
        `;
        return;
      }

      // Placeholder for unproved section
      if (trimmed.startsWith("%% SECTION_BODY_")) {
        html += `
          <div class="coq-line" style="color:#777770; font-style:italic;">
            &nbsp;&nbsp;(* Section ${currentSecIdx} body pending solver execution... *)
          </div>
          <div class="coq-line keyword">Admitted.</div>
        `;
        return;
      }

      // Format line content
      let lineText = SimpleLaTeXRenderer.formatText(line);

      // Syntax highlight Coq keywords
      lineText = lineText.replace(/\b(Proof|Qed|Defined|Theorem|Lemma|Definition|match|with|induction|destruct|reflexivity|intros|rewrite|apply|tauto|discriminate|left|right)\b/g, (m) => {
        if (m === "Proof" || m === "Qed" || m === "Defined" || m === "match" || m === "with") {
          return `<span style="color:#0000cc; font-weight:bold;">${m}</span>`;
        }
        if (m === "Theorem" || m === "Lemma" || m === "Definition") {
          return `<span style="color:#cc4400; font-weight:bold;">${m}</span>`;
        }
        return `<span style="color:#000000;">${m}</span>`;
      });

      const processedClass = inEvaluatedRegion ? "processed" : "";
      html += `<div class="coq-line ${processedClass}">${lineText}</div>`;
    });

    return html;
  }

  static formatText(text) {
    if (!text) return "";
    let s = text;
    s = s.replace(/\$\$([^$]+)\$\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => SimpleLaTeXRenderer.renderMath(g1));
    s = s.replace(/\\textbf\{([^}]+)\}/g, "<strong>$1</strong>");
    s = s.replace(/\\textit\{([^}]+)\}/g, "<em>$1</em>");
    return s;
  }
}

window.SimpleLaTeXRenderer = SimpleLaTeXRenderer;
