/**
 * Mini-Colosseum LaTeX Math & Document Renderer
 * Supports math expressions, theorem environments, section status tinting,
 * and margin annotations for defects.
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

    // High quality offline fallback math renderer
    let s = latex.trim();
    // Common Greek and math symbols
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
      [/\\Leftrightarrow/g, "⇔"],
      [/\\cap/g, "∩"],
      [/\\cup/g, "∪"],
      [/\\mathbb\{R\}/g, "ℝ"],
      [/\\mathbb\{N\}/g, "ℕ"],
      [/\\mathbb\{Z\}/g, "ℤ"],
      [/\\emptyset/g, "∅"],
      [/\\circ/g, "∘"],
    ];

    replacements.forEach(([rgx, rep]) => {
      s = s.replace(rgx, rep);
    });

    // Handle superscripts and subscripts
    s = s.replace(/\^\{([^}]+)\}/g, "<sup>$1</sup>");
    s = s.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    s = s.replace(/_\{([^}]+)\}/g, "<sub>$1</sub>");
    s = s.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");

    // Fractions \frac{a}{b} -> (a / b)
    s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)");

    return `<span class="math-tex" style="font-family: 'Times New Roman', serif; font-style: italic; letter-spacing: 0.3px;">${s}</span>`;
  }

  static renderDocument(latexContent, sectionNodes = [], globalDefects = []) {
    if (!latexContent) {
      return `<div style="color: #888880; font-style: italic; padding: 20px;">No proof document assembled yet.</div>`;
    }

    // Split document into sections or parse sections
    const lines = latexContent.split("\n");
    let html = "";
    let inSection = false;
    let currentSectionIdx = 0;
    let currentSectionTitle = "";
    let currentSectionBody = "";

    const flushSection = () => {
      if (currentSectionIdx > 0 || currentSectionTitle) {
        const secNode = sectionNodes.find(n => (n.output && n.output.section_index === currentSectionIdx) || n.label === `SEC_${currentSectionIdx}` || n.id === `SEC_${currentSectionIdx}`);
        const status = secNode ? secNode.status : "pending";
        const defects = globalDefects.filter(d => d.section_index === currentSectionIdx || d.using_section === currentSectionIdx);

        let defectHtml = "";
        defects.forEach(d => {
          defectHtml += `
            <div class="section-defect-margin">
              <strong>[Global Verifier Defect - ${d.severity.toUpperCase()}]:</strong> ${d.description}
              ${d.suggested_action ? `<br><em>Suggested Action:</em> ${d.suggested_action}` : ""}
            </div>
          `;
        });

        const statusClass = `status-${status}`;
        html += `
          <div class="document-section ${statusClass}" data-section-idx="${currentSectionIdx}">
            <div class="section-header">
              <span>Section ${currentSectionIdx}: ${currentSectionTitle}</span>
              <span class="tag-badge">[${status.toUpperCase()}]</span>
            </div>
            <div class="section-body">${SimpleLaTeXRenderer.formatText(currentSectionBody)}</div>
            ${defectHtml}
          </div>
        `;
      }
      currentSectionBody = "";
    };

    for (const line of lines) {
      const trimmed = line.trim();
      const secMatch = trimmed.match(/^\\section\{([^}]+)\}/);
      if (secMatch) {
        flushSection();
        currentSectionIdx++;
        currentSectionTitle = secMatch[1];
        inSection = true;
      } else if (trimmed.startsWith("\\title{") || trimmed.startsWith("\\documentclass") || trimmed.startsWith("\\maketitle") || trimmed.startsWith("\\begin{document}") || trimmed.startsWith("\\end{document}")) {
        // Document metadata
        if (trimmed.startsWith("\\title{")) {
          const t = trimmed.replace("\\title{", "").replace("}", "");
          html += `<div class="document-header"><div class="document-title">${t}</div></div>`;
        }
      } else if (trimmed.startsWith("%% SECTION_BODY_")) {
        currentSectionBody += `\n<em style="color:#777770;">[Reserved placeholder for section ${currentSectionIdx} body - awaiting solver...]</em>\n`;
      } else {
        if (inSection) {
          currentSectionBody += line + "\n";
        }
      }
    }
    flushSection();

    if (!html) {
      html = `<div class="document-section status-accepted"><div class="section-body">${SimpleLaTeXRenderer.formatText(latexContent)}</div></div>`;
    }

    return html;
  }

  static formatText(text) {
    if (!text) return "";
    let s = text;
    // Render display math $$...$$
    s = s.replace(/\$\$([^$]+)\$\$/g, (m, g1) => {
      return `<div style="text-align: center; margin: 8px 0;">${SimpleLaTeXRenderer.renderMath(g1)}</div>`;
    });
    // Render inline math $...$
    s = s.replace(/\$([^$]+)\$/g, (m, g1) => {
      return SimpleLaTeXRenderer.renderMath(g1);
    });
    // LaTeX bold
    s = s.replace(/\\textbf\{([^}]+)\}/g, "<strong>$1</strong>");
    s = s.replace(/\\textit\{([^}]+)\}/g, "<em>$1</em>");
    return s;
  }
}

window.SimpleLaTeXRenderer = SimpleLaTeXRenderer;
