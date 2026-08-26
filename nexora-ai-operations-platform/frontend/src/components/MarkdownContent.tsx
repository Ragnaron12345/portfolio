import { Fragment, type ReactNode } from "react";

function splitTableRow(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line: string) {
  const cells = splitTableRow(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function repairCollapsedTables(value: string) {
  return value.replace(/\|\s*\|\s*/g, "|\n|");
}

export function stripMarkdownEmphasis(value: string) {
  return value.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/__([^_]+)__/g, "$1").replaceAll("**", "").replaceAll("__", "");
}

function inlineContent(value: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(stripMarkdownEmphasis(value.slice(cursor, match.index)));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if ((token.startsWith("**") && token.endsWith("**")) || (token.startsWith("__") && token.endsWith("__"))) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    cursor = pattern.lastIndex;
  }
  if (cursor < value.length) nodes.push(stripMarkdownEmphasis(value.slice(cursor)));
  return nodes;
}

function isBlockStart(lines: string[], index: number) {
  const line = lines[index]?.trim() ?? "";
  const next = lines[index + 1]?.trim() ?? "";
  return /^(#{1,6})\s+/.test(line)
    || /^>\s?/.test(line)
    || /^[-*+]\s+/.test(line)
    || /^\d+[.)]\s+/.test(line)
    || /^```/.test(line)
    || /^(?:---+|___+|\*\*\*+)$/.test(line)
    || (line.includes("|") && isTableDivider(next));
}

function heading(level: number, content: ReactNode[], key: string) {
  if (level === 1) return <h1 key={key}>{content}</h1>;
  if (level === 2) return <h2 key={key}>{content}</h2>;
  if (level === 3) return <h3 key={key}>{content}</h3>;
  if (level === 4) return <h4 key={key}>{content}</h4>;
  if (level === 5) return <h5 key={key}>{content}</h5>;
  return <h6 key={key}>{content}</h6>;
}

export function MarkdownContent({ text, className = "" }: { text: string; className?: string }) {
  const lines = repairCollapsedTables(text).split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index]?.trim() ?? "";
    if (!line) { index += 1; continue; }

    if (/^```/.test(line)) {
      const language = line.slice(3).trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index]?.trim() ?? "")) {
        code.push(lines[index] ?? "");
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(<pre className="markdown-code-block" key={`code-${index}`}><code data-language={language || undefined}>{code.join("\n")}</code></pre>);
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push(heading(headingMatch[1]!.length, inlineContent(headingMatch[2]!, `heading-${index}`), `heading-${index}`));
      index += 1;
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[index + 1]?.trim() ?? "")) {
      let headers = splitTableRow(line);
      const columnCount = splitTableRow(lines[index + 1] ?? "").length;
      if (headers.length > columnCount) {
        const prefix = headers.slice(0, headers.length - columnCount).join(" · ");
        if (prefix) blocks.push(<p key={`table-prefix-${index}`}>{inlineContent(prefix, `table-prefix-${index}`)}</p>);
        headers = headers.slice(-columnCount);
      }
      while (headers.length < columnCount) headers.push("");
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length) {
        const candidate = lines[index]?.trim() ?? "";
        if (!candidate || !candidate.includes("|") || isTableDivider(candidate)) break;
        rows.push(splitTableRow(candidate));
        index += 1;
      }
      blocks.push(
        <div className="markdown-table-wrap" key={`table-${index}`}>
          <table className="markdown-table">
            <thead><tr>{headers.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{inlineContent(cell, `th-${index}-${cellIndex}`)}</th>)}</tr></thead>
            <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, cellIndex) => <td key={cellIndex}>{inlineContent(row[cellIndex] ?? "—", `td-${index}-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^[-*+]\s+/.test(line) || /^\d+[.)]\s+/.test(line)) {
      const ordered = /^\d+[.)]\s+/.test(line);
      const items: string[] = [];
      const itemPattern = ordered ? /^\d+[.)]\s+/ : /^[-*+]\s+/;
      while (index < lines.length && itemPattern.test(lines[index]?.trim() ?? "")) {
        items.push((lines[index]?.trim() ?? "").replace(itemPattern, ""));
        index += 1;
      }
      const children = items.map((item, itemIndex) => <li key={`${itemIndex}-${item}`}>{inlineContent(item, `li-${index}-${itemIndex}`)}</li>);
      blocks.push(ordered ? <ol key={`list-${index}`}>{children}</ol> : <ul key={`list-${index}`}>{children}</ul>);
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index]?.trim() ?? "")) {
        quote.push((lines[index]?.trim() ?? "").replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${index}`}>{quote.map((part, partIndex) => <Fragment key={partIndex}>{partIndex ? <br /> : null}{inlineContent(part, `quote-${index}-${partIndex}`)}</Fragment>)}</blockquote>);
      continue;
    }

    if (/^(?:---+|___+|\*\*\*+)$/.test(line)) {
      blocks.push(<hr key={`rule-${index}`} />);
      index += 1;
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length) {
      const candidate = lines[index]?.trim() ?? "";
      if (!candidate || isBlockStart(lines, index)) break;
      paragraph.push(candidate);
      index += 1;
    }
    const content = paragraph.join(" ");
    blocks.push(<p key={`paragraph-${index}`}>{inlineContent(content, `paragraph-${index}`)}</p>);
  }

  return <div className={`markdown-content ${className}`.trim()}>{blocks}</div>;
}
