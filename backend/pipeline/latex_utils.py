"""Deterministic LaTeX & JSON sanitization, extraction, and assembly utilities."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# LaTeX command stems that start with b, f, t, r, n and collide with JSON escape chars
_LATEX_B_STEMS = (
    r"eta\b|inom\b|ig(?:ger|gest|l|r|m|g|gl|gr|gm)?\b|ar\b|f\b|m\b|egin\b|ox\b|"
    r"ullet\b|ackslash\b|ot\b|igcup\b|igcap\b|igoplus\b|igotimes\b|igvee\b|igwedge\b|"
    r"iguplus\b|igodot\b|mod\b|lacksquare\b|lacktriangle\b|bbd\b|inom\b|reve\b"
)
_LATEX_F_STEMS = r"rac\b|orall\b|lat\b|rown\b|box\b|ill\b|ootnote"
_LATEX_T_STEMS = (
    r"heta\b|imes\b|o\b|ext(?:bf|it|rm|sf|tt|up|normal)?\b|au\b|frac\b|"
    r"riangle(?:left|right|q)?\b|ilde\b|ag\b|op\b|an\b|anh\b|herefore\b|iny\b"
)
_LATEX_R_STEMS = (
    r"ho\b|ight(?:arrow|harpoondown|harpoonup|leftarrows|leftharpoons|squigarrow)?|"
    r"floor\b|ceil\b|angle\b|m\b|ule\b|aise\b|enewcommand\b|estriction\b"
)
_LATEX_N_STEMS = (
    r"eq\b|e\b|otin\b|ot\b|u\b|abla\b|atural\b|ewline\b|ewtheorem\b|ocite\b|"
    r"onumber\b|ormalfont\b|orm\b|oindent\b|i\b|mid\b|parallel\b|vdash\b|cong\b|"
    r"sim\b|subseteq\b|supseteq\b|less\b|gtr\b|leq\b|geq\b|prec\b|succ\b"
)

_AMBIGUOUS_JSON_LATEX_RE = re.compile(
    r'(?<!\\)\\(?:'
    rf'b(?=(?:{_LATEX_B_STEMS}))|'
    rf'f(?=(?:{_LATEX_F_STEMS}))|'
    rf't(?=(?:{_LATEX_T_STEMS}))|'
    rf'r(?=(?:{_LATEX_R_STEMS}))|'
    rf'n(?=(?:{_LATEX_N_STEMS}))'
    r')'
)

# Backslash followed by any character that is NOT a valid JSON escape (", \, /, b, f, n, r, t, uXXXX)
_INVALID_JSON_ESCAPE_RE = re.compile(
    r'(?<!\\)\\(?!(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))'
)

# Double-escaped LaTeX commands produced when a raw JSON string was not unescaped
_DOUBLE_ESCAPED_LATEX_CMD_RE = re.compile(
    r'\\\\(?=[A-Za-z]+|\{|\}|\[|\]|\(|\)|,|;|:|!|\||\s|\$)'
)

# Literal \n not followed by a valid \n... LaTeX command stem
_LITERAL_SLASH_N_RE = re.compile(
    rf'\\n(?!(?:{_LATEX_N_STEMS}|[A-Za-z]))'
)

# Unicode math replacements for clean pdflatex compilation
_UNICODE_TO_LATEX: List[Tuple[str, str]] = [
    ("âˆŽ", r"\hfill$\blacksquare$"),
    ("\u220e", r"\hfill$\blacksquare$"),  # ∎
    ("\u25a0", r"\hfill$\blacksquare$"),  # ■
    ("\u25a1", r"\hfill$\square$"),       # □
    ("≥", r"\ge "),
    ("≤", r"\le "),
    ("≠", r"\neq "),
    ("∈", r"\in "),
    ("∉", r"\notin "),
    ("⊂", r"\subset "),
    ("⊆", r"\subseteq "),
    ("⊊", r"\subsetneq "),
    ("⊃", r"\supset "),
    ("⊇", r"\supseteq "),
    ("∪", r"\cup "),
    ("∩", r"\cap "),
    ("×", r"\times "),
    ("·", r"\cdot "),
    ("→", r"\to "),
    ("←", r"\leftarrow "),
    ("↔", r"\leftrightarrow "),
    ("⇒", r"\Rightarrow "),
    ("⇐", r"\Leftarrow "),
    ("⇔", r"\Leftrightarrow "),
    ("↦", r"\mapsto "),
    ("∞", r"\infty "),
    ("∀", r"\forall "),
    ("∃", r"\exists "),
    ("∅", r"\emptyset "),
    ("±", r"\pm "),
    ("∓", r"\mp "),
    ("≈", r"\approx "),
    ("≡", r"\equiv "),
    ("≅", r"\cong "),
    ("∼", r"\sim "),
    ("≃", r"\simeq "),
    ("∝", r"\propto "),
    ("∂", r"\partial "),
    ("∇", r"\nabla "),
    ("⟨", r"\langle "),
    ("⟩", r"\rangle "),
    ("⌊", r"\lfloor "),
    ("⌋", r"\rfloor "),
    ("⌈", r"\lceil "),
    ("⌉", r"\rceil "),
    ("⊕", r"\oplus "),
    ("⊗", r"\otimes "),
    ("⊥", r"\perp "),
    ("∥", r"\parallel "),
    ("∣", r"\mid "),
    ("∤", r"\nmid "),
    ("α", r"\alpha "),
    ("β", r"\beta "),
    ("γ", r"\gamma "),
    ("δ", r"\delta "),
    ("ε", r"\varepsilon "),
    ("ζ", r"\zeta "),
    ("η", r"\eta "),
    ("θ", r"\theta "),
    ("ι", r"\iota "),
    ("κ", r"\kappa "),
    ("λ", r"\lambda "),
    ("μ", r"\mu "),
    ("ν", r"\nu "),
    ("ξ", r"\xi "),
    ("π", r"\pi "),
    ("ρ", r"\rho "),
    ("σ", r"\sigma "),
    ("τ", r"\tau "),
    ("υ", r"\upsilon "),
    ("φ", r"\varphi "),
    ("χ", r"\chi "),
    ("ψ", r"\psi "),
    ("ω", r"\omega "),
    ("Γ", r"\Gamma "),
    ("Δ", r"\Delta "),
    ("Θ", r"\Theta "),
    ("Λ", r"\Lambda "),
    ("Ξ", r"\Xi "),
    ("Π", r"\Pi "),
    ("Σ", r"\Sigma "),
    ("Φ", r"\Phi "),
    ("Ψ", r"\Psi "),
    ("Ω", r"\Omega "),
    ("“", "``"),
    ("”", "''"),
    ("‘", "`"),
    ("’", "'"),
    ("—", "---"),
    ("–", "--"),
]


def repair_json_latex_escapes(text: str) -> str:
    """Safely double single-escaped LaTeX backslashes inside a JSON string."""
    if not text or "\\" not in text:
        return text
    fixed = _AMBIGUOUS_JSON_LATEX_RE.sub(lambda m: "\\" + m.group(0), text)
    fixed = _INVALID_JSON_ESCAPE_RE.sub(r"\\\\", fixed)
    return fixed


def _unescape_json_string_fragment(raw_fragment: str) -> str:
    """Unescape a JSON string value fragment (even if truncated mid-string)."""
    if not raw_fragment:
        return ""
    frag = raw_fragment
    # Strip trailing lone backslash if cut off mid-escape
    if frag.endswith("\\") and not frag.endswith("\\\\"):
        frag = frag[:-1]
    # Protect ambiguous LaTeX escapes before json.loads
    repaired = repair_json_latex_escapes(frag)
    try:
        return json.loads(f'"{repaired}"')
    except Exception:
        pass
    # Manual fallback unescaping
    out: List[str] = []
    i = 0
    n = len(frag)
    while i < n:
        ch = frag[i]
        if ch == "\\" and i + 1 < n:
            nxt = frag[i + 1]
            if nxt == '"':
                out.append('"')
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "/":
                out.append("/")
                i += 2
                continue
            if nxt == "n":
                # Check if \n is actually a LaTeX macro like \neq, \notin, \nu
                rest = frag[i + 1 :]
                if re.match(rf"n(?:{_LATEX_N_STEMS})", rest):
                    out.append("\\n")
                else:
                    out.append("\n")
                i += 2
                continue
            if nxt == "t":
                rest = frag[i + 1 :]
                if re.match(rf"t(?:{_LATEX_T_STEMS})", rest):
                    out.append("\\t")
                else:
                    out.append("\t")
                i += 2
                continue
            if nxt == "r":
                rest = frag[i + 1 :]
                if re.match(rf"r(?:{_LATEX_R_STEMS})", rest):
                    out.append("\\r")
                else:
                    out.append("\r")
                i += 2
                continue
            if nxt == "b":
                rest = frag[i + 1 :]
                if re.match(rf"b(?:{_LATEX_B_STEMS})", rest):
                    out.append("\\b")
                else:
                    out.append("\\b")
                i += 2
                continue
            if nxt == "f":
                out.append("\\f")
                i += 2
                continue
            if nxt == "u" and i + 5 < n and re.match(r"[0-9a-fA-F]{4}", frag[i + 2 : i + 6]):
                code = int(frag[i + 2 : i + 6], 16)
                out.append(chr(code))
                i += 6
                continue
            # Otherwise preserve backslash + char (e.g. \subset -> \subset)
            out.append("\\" + nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_json_string_value(text: str, start_after_quote: int) -> Tuple[str, bool]:
    """Scan a JSON string value starting right after its opening quote.

    Returns (raw_inner_content, was_closed).
    """
    i = start_after_quote
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return text[start_after_quote:i], True
        i += 1
    return text[start_after_quote:], False


def extract_fields_from_truncated_json(text: str) -> Dict[str, Any]:
    """Recover fields from a truncated or malformed JSON response."""
    if not text or not isinstance(text, str):
        return {}
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()

    # First try full JSON parse with LaTeX escape repair
    for candidate in (stripped, repair_json_latex_escapes(stripped)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    result: Dict[str, Any] = {}
    string_keys = (
        "status",
        "solution_body",
        "latex_body",
        "revised_latex",
        "latex_skeleton",
        "claimed_result",
        "primary_route",
        "key_obstruction",
        "conjecture",
        "rationale",
        "explanation",
        "verdict",
        "summary",
        "raw_markdown",
        "problem_type",
        "Target_Claim",
        "Proposed_Construction",
        "Key_Lemma",
        "First_Failure_Point",
        "Viability_Estimate",
    )
    for key in string_keys:
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"', stripped)
        if m:
            raw_val, _ = _scan_json_string_value(stripped, m.end())
            result[key] = _unescape_json_string_fragment(raw_val)

    # Boolean keys
    for bkey in ("approved", "survived", "passed", "resolved"):
        m = re.search(rf'"{re.escape(bkey)}"\s*:\s*(true|false)\b', stripped, re.IGNORECASE)
        if m:
            result[bkey] = m.group(1).lower() == "true"

    # Integer keys
    for ikey in ("section_index", "index", "round_id"):
        m = re.search(rf'"{re.escape(ikey)}"\s*:\s*(\d+)\b', stripped)
        if m:
            result[ikey] = int(m.group(1))

    return result


def _repair_control_char_corruptions(text: str) -> str:
    """Restore LaTeX commands corrupted when json.loads turned \\b, \\f, \\t, \\r into control chars."""
    if not text:
        return ""
    # \x08 is ASCII backspace (from \beta, \binom, \big, \bar, \bf, \bm, \begin, \box, \bullet, \blacksquare)
    text = text.replace("\x08", "\\b")
    # \x0c is ASCII formfeed (from \frac, \forall, \flat, \frown, \fbox, \fill)
    text = text.replace("\x0c", "\\f")
    # \x09 is tab — restore when followed by a LaTeX \t... stem
    text = re.sub(rf"\x09(?=(?:{_LATEX_T_STEMS}))", r"\\t", text)
    # \x0d is CR (not followed by \n) — restore when followed by a LaTeX \r... stem
    text = re.sub(rf"\x0d(?=(?:{_LATEX_R_STEMS}))", r"\\r", text)
    return text


def _unescape_double_escaped_latex(text: str) -> str:
    """Convert raw JSON-escaped LaTeX (`\\\\subset`, `\\\\mathbf`, `\\n\\n`) into valid LaTeX."""
    if not text:
        return ""
    out = text
    # Replace \u220e / \u25a0 / \u25a1 written as literal text
    out = re.sub(r"\\+u220[eE]", r"\\hfill$\\blacksquare$", out)
    out = re.sub(r"\\+u25a0", r"\\hfill$\\blacksquare$", out)
    out = re.sub(r"\\+u25a1", r"\\hfill$\\square$", out)
    # Replace literal \n (not part of \neq, \notin, \nu, \nabla, etc.) with actual newlines
    if "\\n" in out:
        out = _LITERAL_SLASH_N_RE.sub("\n", out)
    # Replace \\<command> with \<command> when double-escaping is detected
    # Note: In valid LaTeX, `\\` followed by a letter (with no space) only happens inside
    # tabular/align if someone wrote `\\a` without space, whereas `\\subset`, `\\mathbf`, `\\frac`
    # are always double-escaped JSON backslashes.
    out = re.sub(r"\\\\(?=[A-Za-z]+)", r"\\", out)
    # Also unescape `\\{`, `\\}`, `\\(`, `\\)`, `\\,`, `\\;`, `\\!`, `\\|` when double-escaped
    out = re.sub(r"\\\\(?=[\{\}\(\),;!\|])", r"\\", out)
    return out


def _strip_duplicate_section_header(body: str, section_title: str = "") -> str:
    """Remove a leading \\section{...} from a section body so it doesn't duplicate the skeleton header."""
    if not body:
        return ""
    stripped = body.lstrip()
    m = re.match(r"^\\section\*?\{((?:[^{}]|\{[^{}]*\})*)\}\s*", stripped)
    if m:
        return stripped[m.end() :].lstrip()
    if section_title:
        # Also strip markdown # Section Title if present at top
        md_m = re.match(r"^#{1,3}\s+([^\n]+)\n+", stripped)
        if md_m and section_title.lower()[:20] in md_m.group(1).lower():
            return stripped[md_m.end() :].lstrip()
    return body


def _format_plain_theorem_blocks(text: str) -> str:
    """Format plain-text 'Lemma X.', 'Theorem X.', 'Proof.' headers cleanly for LaTeX if not already wrapped."""
    if not text:
        return ""
    # Convert markdown bold **...** to \textbf{...}
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\\textbf{\1}", text)
    # Ensure paragraphs starting with plain `Lemma 1.2 (Name).` or `Theorem 3.` or `Proof.` have bold/italic lead-ins
    # when not already using \begin{lemma} or \textbf{Lemma}
    text = re.sub(
        r"(?m)^((?:Lemma|Theorem|Proposition|Corollary|Definition|Claim|Remark)\s+\d+(?:\.\d+)*(?:\s*\([^)\n]+\))?\.)\s+",
        r"\\par\\smallskip\\noindent\\textbf{\1} ",
        text,
    )
    text = re.sub(
        r"(?m)^(Proof(?:\s+of\s+[^\n.]+)?\.)\s+",
        r"\\par\\smallskip\\noindent\\textit{\1} ",
        text,
    )
    return text


def _clean_truncated_tail(text: str) -> str:
    """Clean up dangling backslashes or incomplete tokens at the very end of a truncated section."""
    if not text:
        return ""
    s = text.rstrip()
    # If ends with a lone backslash or incomplete macro at EOF (e.g. `\max_{j<K_1}\` or `at most $`)
    if s.endswith("\\") and not s.endswith("\\\\"):
        s = s[:-1].rstrip()
    # If ends right after an opening `$` with nothing after it (like `In all cases at most $`)
    if s.endswith("$") and not s.endswith("\\$"):
        # Count unescaped `$` in the last paragraph
        last_para = s.split("\n\n")[-1]
        single_dollars = len(re.findall(r"(?<!\\)(?<!\$)\$(?!\$)", last_para))
        if single_dollars % 2 == 1:
            s = s[:-1].rstrip()
    return s


def _balance_math_and_braces_in_paragraph(para: str) -> str:
    """Ensure a paragraph does not leave inline math `$`, `\\(`, `\\[`, or braces `{` unclosed."""
    if not para.strip():
        return para
    s = para
    # Strip trailing single backslash
    if s.endswith("\\") and not s.endswith("\\\\"):
        s = s[:-1]

    # Balance display math \[ ... \]
    opens_bracket = len(re.findall(r"(?<!\\)\\\[", s))
    closes_bracket = len(re.findall(r"(?<!\\)\\\]", s))
    if opens_bracket > closes_bracket:
        s += r" \]" * (opens_bracket - closes_bracket)

    # Balance inline math \( ... \)
    opens_paren = len(re.findall(r"(?<!\\)\\\(", s))
    closes_paren = len(re.findall(r"(?<!\\)\\\)", s))
    if opens_paren > closes_paren:
        s += r"\)" * (opens_paren - closes_paren)

    # Balance $$ ... $$
    double_dollars = len(re.findall(r"(?<!\\)\$\$", s))
    if double_dollars % 2 == 1:
        s += "$$"

    # Count single unescaped `$` (not part of `$$`)
    # First check braces inside open math or paragraph
    single_dollar_positions = [
        m.start() for m in re.finditer(r"(?<!\\)(?<!\$)\$(?!\$)", s)
    ]
    if len(single_dollar_positions) % 2 == 1:
        last_pos = single_dollar_positions[-1]
        tail = s[last_pos + 1 :]
        # If the unclosed `$` is at the very end of the paragraph with nothing inside, remove it
        if not tail.strip():
            s = s[:last_pos].rstrip()
        else:
            # Close any unclosed `{` inside the math tail before closing `$`
            open_b = 0
            i = 0
            while i < len(tail):
                if tail[i] == "\\":
                    i += 2
                    continue
                if tail[i] == "{":
                    open_b += 1
                elif tail[i] == "}":
                    open_b = max(0, open_b - 1)
                i += 1
            if open_b > 0:
                s += "}" * open_b
            s += "$"

    # Balance unescaped `{` and `}` across the paragraph (ignoring `\begin` / `\end`)
    open_braces = 0
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "{":
            open_braces += 1
        elif s[i] == "}":
            open_braces = max(0, open_braces - 1)
        i += 1
    if open_braces > 0:
        s += "}" * open_braces

    return s


def _close_unclosed_environments(text: str) -> str:
    """Close any unclosed \\begin{env} environments in reverse order."""
    env_stack: List[str] = []
    for m in re.finditer(r"\\(begin|end)\{([A-Za-z0-9*]+)\}", text):
        kind, env = m.group(1), m.group(2)
        if env == "document":
            continue
        if kind == "begin":
            env_stack.append(env)
        else:
            if env in env_stack:
                # Pop most recent matching env
                idx = len(env_stack) - 1 - env_stack[::-1].index(env)
                env_stack.pop(idx)
    if env_stack:
        closers = "\n" + "\n".join(f"\\end{{{env}}}" for env in reversed(env_stack))
        return text + closers
    return text


def sanitize_latex_body(body: str, section_title: str = "") -> str:
    """Sanitize a section body so it is guaranteed valid, readable LaTeX without JSON wrappers or unclosed math."""
    if not body or not isinstance(body, str):
        return ""

    text = body.strip()

    # 1. If the body is a raw or truncated JSON object (e.g. `{"status": "solved", "solution_body": "...`),
    # extract the inner LaTeX body!
    if text.startswith("{") and any(
        k in text[:200] for k in ('"solution_body"', '"latex_body"', '"status"', '"revised_latex"')
    ):
        extracted = extract_fields_from_truncated_json(text)
        inner = (
            extracted.get("solution_body")
            or extracted.get("latex_body")
            or extracted.get("revised_latex")
            or ""
        )
        if inner:
            text = str(inner).strip()

    # 2. Repair ASCII control characters from JSON unescaping (\x08 -> \b, \x0c -> \f, etc.)
    text = _repair_control_char_corruptions(text)

    # 3. Unescape double-escaped LaTeX (`\\subset` -> `\subset`, `\n\n` -> newline, `\u220e` -> `\hfill$\blacksquare$`)
    text = _unescape_double_escaped_latex(text)

    # 4. Replace raw Unicode math symbols and mojibake with LaTeX macros
    for uni, latex_rep in _UNICODE_TO_LATEX:
        if uni in text:
            text = text.replace(uni, latex_rep)

    # 5. Strip duplicate leading \section{...} if it repeats the section heading
    text = _strip_duplicate_section_header(text, section_title=section_title)

    # 6. Clean truncated tail and format plain theorem/lemma/proof lead-ins
    text = _clean_truncated_tail(text)
    text = _format_plain_theorem_blocks(text)

    # 7. Balance inline math `$ ... $` and `{ ... }` per paragraph so an unclosed `$` never bleeds across sections
    paragraphs = re.split(r"(\n\s*\n)", text)
    balanced_parts: List[str] = []
    for part in paragraphs:
        if re.fullmatch(r"\n\s*\n", part):
            balanced_parts.append("\n\n")
        else:
            balanced_parts.append(_balance_math_and_braces_in_paragraph(part))
    text = "".join(balanced_parts)

    # 8. Close any unclosed \begin{...} environments
    text = _close_unclosed_environments(text)

    return text.strip()


def _extract_subproblem_tuple(sp: Any, pos: int) -> Tuple[int, str]:
    """Return (index, title) from a SectionSpec or dict."""
    if isinstance(sp, dict):
        raw_idx = sp.get("index")
        idx = int(raw_idx) if isinstance(raw_idx, int) and raw_idx > 0 else pos
        title = str(sp.get("title") or f"Section {idx}").strip()
        return idx, title
    raw_idx = getattr(sp, "index", None)
    idx = int(raw_idx) if isinstance(raw_idx, int) and raw_idx > 0 else pos
    title = str(getattr(sp, "title", None) or f"Section {idx}").strip()
    return idx, title


def canonicalize_latex_skeleton(
    skeleton: str,
    subproblems: List[Any],
    problem_title: str = "",
) -> str:
    """Ensure the LaTeX skeleton has a clean preamble and 1-to-1 aligned \\section{title} + %% SECTION_BODY_k %%."""
    if not subproblems:
        return skeleton or ""

    # Preserve minimal non-LaTeX test skeletons (e.g., unit tests with "head\n%% SECTION_BODY_1 %%...")
    if skeleton and "\\documentclass" not in skeleton and "\\begin{document}" not in skeleton and "\\section" not in skeleton:
        return skeleton

    # Extract title from existing skeleton if present
    title_text = problem_title.strip() if problem_title else ""
    if skeleton:
        m_title = re.search(r"\\title\{((?:[^{}]|\{[^{}]*\})+)\}", skeleton)
        if m_title and not title_text:
            title_text = m_title.group(1).strip()
    if not title_text:
        title_text = "Mathematical Proof and Analysis"

    # Extract abstract if present in skeleton
    abstract_block = ""
    if skeleton:
        m_abs = re.search(r"(\\begin\{abstract\}.*?\\end\{abstract\})", skeleton, re.DOTALL)
        if m_abs:
            abstract_block = m_abs.group(1).strip() + "\n\n"

    sections_lines: List[str] = []
    for pos, sp in enumerate(subproblems, start=1):
        idx, sp_title = _extract_subproblem_tuple(sp, pos)
        # Sanitize title math/unicode
        for uni, latex_rep in _UNICODE_TO_LATEX:
            if uni in sp_title:
                sp_title = sp_title.replace(uni, latex_rep)
        sections_lines.append(f"\\section{{{sp_title}}}\n%% SECTION_BODY_{idx} %%")

    sections_str = "\n\n".join(sections_lines)

    return (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage{amsmath,amssymb,amsthm,mathtools}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\usepackage[colorlinks=true,linkcolor=blue,citecolor=blue,urlcolor=blue]{hyperref}\n\n"
        "\\newtheorem{theorem}{Theorem}[section]\n"
        "\\newtheorem{lemma}[theorem]{Lemma}\n"
        "\\newtheorem{proposition}[theorem]{Proposition}\n"
        "\\newtheorem{corollary}[theorem]{Corollary}\n"
        "\\newtheorem{claim}[theorem]{Claim}\n"
        "\\theoremstyle{definition}\n"
        "\\newtheorem{definition}[theorem]{Definition}\n"
        "\\theoremstyle{remark}\n"
        "\\newtheorem{remark}[theorem]{Remark}\n\n"
        f"\\title{{{title_text}}}\n"
        "\\author{Colosseum Mathematical Research Agent}\n"
        "\\date{\\today}\n\n"
        "\\begin{document}\n"
        "\\maketitle\n\n"
        f"{abstract_block}"
        f"{sections_str}\n\n"
        "\\end{document}\n"
    )


def assemble_latex_document(
    plan: Any,
    completed_bodies: Dict[int, str],
    problem_title: str = "",
) -> str:
    """Assemble a complete, clean LaTeX document from a SectionPlan and section bodies."""
    if isinstance(plan, dict):
        raw_skeleton = str(plan.get("latex_skeleton") or "")
        subproblems = list(plan.get("subproblems") or [])
    else:
        raw_skeleton = str(getattr(plan, "latex_skeleton", "") or "")
        subproblems = list(getattr(plan, "subproblems", []) or [])

    # Check if this is a minimal test skeleton (no \documentclass / \begin{document})
    is_test_skeleton = (
        bool(raw_skeleton)
        and "\\documentclass" not in raw_skeleton
        and "\\begin{document}" not in raw_skeleton
        and "\\section" not in raw_skeleton
    )

    if is_test_skeleton:
        assembled = raw_skeleton
        for pos, sp in enumerate(subproblems, start=1):
            idx, sp_title = _extract_subproblem_tuple(sp, pos)
            body = sanitize_latex_body(completed_bodies.get(idx, ""), section_title=sp_title)
            placeholder = f"%% SECTION_BODY_{idx} %%"
            if placeholder in assembled:
                assembled = assembled.replace(placeholder, body)
            else:
                assembled += f"\n\n\\section{{{sp_title}}}\n{body}"
        return assembled

    # For full LaTeX documents, always canonicalize the skeleton so section headers and
    # placeholders match 1-to-1 with subproblems[0..N-1] and no off-by-one shift can occur.
    skeleton = canonicalize_latex_skeleton(raw_skeleton, subproblems, problem_title=problem_title)
    assembled = skeleton
    for pos, sp in enumerate(subproblems, start=1):
        idx, sp_title = _extract_subproblem_tuple(sp, pos)
        raw_body = completed_bodies.get(idx, "")
        clean_body = sanitize_latex_body(raw_body, section_title=sp_title)
        if not clean_body:
            clean_body = "% Section pending completion."
        placeholder = f"%% SECTION_BODY_{idx} %%"
        if placeholder in assembled:
            assembled = assembled.replace(placeholder, clean_body)
        elif "\\end{document}" in assembled:
            assembled = assembled.replace(
                "\\end{document}",
                f"\\section{{{sp_title}}}\n{clean_body}\n\n\\end{{document}}",
            )
        else:
            assembled += f"\n\n\\section{{{sp_title}}}\n{clean_body}"

    return assembled

