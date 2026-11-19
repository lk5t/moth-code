/** 2.0: line diff (LCS) for the before/after view. */
export type DiffRow =
  | { t: "same"; a: number; b: number; text: string }
  | { t: "del"; a: number; text: string }
  | { t: "add"; b: number; text: string };

const MAX_CELLS = 4_000_000;

export function diffLines(before: string, after: string): DiffRow[] {
  const A = before === "" ? [] : before.replace(/\r\n/g, "\n").split("\n");
  const B = after === "" ? [] : after.replace(/\r\n/g, "\n").split("\n");
  // trim the common start and end so big files with small edits stay cheap
  let s = 0;
  while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let e = 0;
  while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
  const a = A.slice(s, A.length - e), b = B.slice(s, B.length - e);
  const rows: DiffRow[] = [];
  for (let i = 0; i < s; i++) rows.push({ t: "same", a: i + 1, b: i + 1, text: A[i] });
  if (a.length * b.length > MAX_CELLS) {  // too big to align: show it as replaced
    a.forEach((text, i) => rows.push({ t: "del", a: s + i + 1, text }));
    b.forEach((text, i) => rows.push({ t: "add", b: s + i + 1, text }));
  } else {
    const n = a.length, m = b.length;
    const L: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && a[i] === b[j]) { rows.push({ t: "same", a: s + i + 1, b: s + j + 1, text: a[i] }); i++; j++; }
      else if (i < n && (j >= m || L[i + 1][j] >= L[i][j + 1])) { rows.push({ t: "del", a: s + i + 1, text: a[i] }); i++; }
      else { rows.push({ t: "add", b: s + j + 1, text: b[j] }); j++; }
    }
  }
  for (let k = 0; k < e; k++) rows.push({ t: "same", a: A.length - e + k + 1, b: B.length - e + k + 1, text: A[A.length - e + k] });
  return rows;
}

export function diffStats(rows: DiffRow[]) {
  return { added: rows.filter((r) => r.t === "add").length, removed: rows.filter((r) => r.t === "del").length };
}

/** Side-by-side pairs: deletions and additions next to each other line up in one row. */
export function sideBySide(rows: DiffRow[]): { left?: DiffRow; right?: DiffRow }[] {
  const out: { left?: DiffRow; right?: DiffRow }[] = [];
  for (let i = 0; i < rows.length;) {
    const r = rows[i];
    if (r.t === "same") { out.push({ left: r, right: r }); i++; continue; }
    const dels: DiffRow[] = [], adds: DiffRow[] = [];
    while (i < rows.length && rows[i].t === "del") dels.push(rows[i++]);
    while (i < rows.length && rows[i].t === "add") adds.push(rows[i++]);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) out.push({ left: dels[k], right: adds[k] });
  }
  return out;
}

/** Hide long unchanged stretches, keeping a few lines of context around each change. */
export function folded<T extends { left?: DiffRow; right?: DiffRow }>(pairs: T[], context = 3): (T | { skip: number })[] {
  const changed = pairs.map((p) => p.left?.t !== "same" || p.right?.t !== "same");
  const keep = changed.map((_, i) => changed.slice(Math.max(0, i - context), i + context + 1).some(Boolean));
  const out: (T | { skip: number })[] = [];
  for (let i = 0; i < pairs.length;) {
    if (keep[i]) { out.push(pairs[i++]); continue; }
    let j = i;
    while (j < pairs.length && !keep[j]) j++;
    out.push({ skip: j - i });
    i = j;
  }
  return out;
}
