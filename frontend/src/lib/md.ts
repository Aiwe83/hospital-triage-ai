/**
 * Renderer mínimo de Markdown → HTML.
 *
 * Alcance: handbooks README / CLAUDE servidos por `/handbook/{name}`.
 * Evita meter una dependencia de markdown para lo que en esencia son tres
 * páginas de texto estático. Soporta las construcciones que realmente
 * usan esos archivos:
 *   - Headers ATX (#, ##, ###)
 *   - Bloques de código con fences (``` lang)
 *   - Código inline
 *   - Bold (**x**) e italic (*x* / _x_)
 *   - Enlaces [text](url)
 *   - Listas no ordenadas y ordenadas
 *   - Tablas pipe estilo GitHub con fila separadora
 *   - Blockquote, regla horizontal, párrafos planos
 *
 * Cualquier cosa fuera de eso cae a párrafo para que nunca se pierda
 * contenido en silencio. La salida está saneada — solo llegan al DOM las
 * etiquetas explícitas que emite este renderer.
 */

const escapeHtml = (s: string): string =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const renderInline = (s: string): string => {
  let out = escapeHtml(s);
  // Código inline primero para que su contenido no se reparsee como bold/italic.
  out = out.replace(/`([^`\n]+)`/g, (_, code) => `<code class="md-code">${code}</code>`);
  // Bold (**x**) antes de italic para que los asteriscos no se matcheen parcialmente.
  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  out = out.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  // Enlaces — escape ya aplicado, pero extraemos la URL cruda en la que vamos a confiar.
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
    const safeUrl = url.replace(/"/g, "%22");
    return `<a class="md-link" href="${safeUrl}" target="_blank" rel="noreferrer noopener">${label}</a>`;
  });
  return out;
};

const renderTable = (rows: string[]): string => {
  const parseRow = (line: string): string[] =>
    line
      .replace(/^\s*\|/, "")
      .replace(/\|\s*$/, "")
      .split("|")
      .map((c) => c.trim());

  const header = parseRow(rows[0]);
  const body = rows.slice(2).map(parseRow);
  const th = header.map((c) => `<th>${renderInline(c)}</th>`).join("");
  const tr = body
    .map((r) => `<tr>${r.map((c) => `<td>${renderInline(c)}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="md-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
};

export function renderMarkdown(input: string): string {
  const lines = input.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Bloque de código con fences.
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const lang = fence[1] || "";
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // saltar el fence de cierre
      out.push(
        `<pre class="md-pre" data-lang="${escapeHtml(lang)}"><code>${escapeHtml(buf.join("\n"))}</code></pre>`,
      );
      continue;
    }

    // Headers ATX.
    const h = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (h) {
      const level = h[1].length;
      out.push(`<h${level} class="md-h md-h${level}">${renderInline(h[2])}</h${level}>`);
      i++;
      continue;
    }

    // Regla horizontal.
    if (/^\s*---\s*$/.test(line)) {
      out.push('<hr class="md-hr" />');
      i++;
      continue;
    }

    // Tabla pipe (cabecera + separador + filas).
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*[-:|\s]+\|[-:|\s]*\s*$/.test(lines[i + 1])) {
      const tbl: string[] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        tbl.push(lines[i]);
        i++;
      }
      out.push(renderTable(tbl));
      continue;
    }

    // Blockquote.

    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      out.push(`<blockquote class="md-bq">${renderInline(buf.join(" "))}</blockquote>`);
      continue;
    }

    // Listas (no ordenadas y ordenadas, agrupadas mientras sean contiguas).
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, ""));
        i++;
      }
      const li = items.map((it) => `<li>${renderInline(it)}</li>`).join("");
      out.push(ordered ? `<ol class="md-ol">${li}</ol>` : `<ul class="md-ul">${li}</ul>`);
      continue;
    }

    // Línea en blanco — separador.
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Párrafo plano (recoger líneas contiguas no especiales).
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,6}\s|```|>\s|\s*[-*]\s|\s*\d+\.\s|\s*\|)/.test(lines[i]) && !/^\s*---\s*$/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    if (para.length) {
      out.push(`<p class="md-p">${renderInline(para.join(" "))}</p>`);
    }
  }

  return out.join("\n");
}
