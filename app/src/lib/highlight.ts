/** 2.0: small, safe syntax highlighter for chat code blocks (no HTML strings: returns tokens React renders). */
export type TokenKind = "kw" | "str" | "com" | "num" | "fn" | "type" | "plain";
export interface Token { k: TokenKind; v: string }

const KW: Record<string, string> = {
  py: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case self",
  js: "await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof undefined var void while with yield async of static get set interface type enum implements private public protected readonly as",
  sh: "if then else elif fi for while do done case esac in function return local export echo exit set unset sudo cd source",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false",
  c: "auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false NULL nullptr class public private protected template typename namespace using new delete include define",
  rs: "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
  java: "abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new null package private protected public return short static super switch this throw throws try void volatile while true false var",
  sql: "select from where and or not insert into values update set delete create table drop alter index join left right inner outer on group by order having limit offset as distinct union all null is in like between primary key foreign references",
  ps: "function param if else elseif foreach for while do switch return try catch finally throw begin process end",
};
const ALIAS: Record<string, string> = {
  python: "py", py: "py", javascript: "js", js: "js", jsx: "js", typescript: "js", ts: "js", tsx: "js", json: "js",
  bash: "sh", sh: "sh", shell: "sh", zsh: "sh", console: "sh", go: "go", golang: "go", c: "c", h: "c", cpp: "c", "c++": "c", cc: "c",
  csharp: "java", cs: "java", rust: "rs", rs: "rs", java: "java", kotlin: "java", kt: "java", sql: "sql", powershell: "ps", ps1: "ps",
};
const HASH_COMMENT = new Set(["py", "sh", "ps"]);

export function langOf(label: string): string {
  return ALIAS[label.trim().toLowerCase().split(/\s+/)[0]] ?? "";
}

export function highlight(code: string, label: string): Token[] {
  const lang = langOf(label);
  if (!lang) return [{ k: "plain", v: code }];
  const kws = new Set(KW[lang].split(" "));
  const ci = lang === "sql";
  const comment = HASH_COMMENT.has(lang) ? "#[^\\n]*" : lang === "sql" ? "--[^\\n]*" : "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/";
  const strings = lang === "py" ? `"""[\\s\\S]*?"""|'''[\\s\\S]*?'''|"(?:\\\\.|[^"\\\\\\n])*"|'(?:\\\\.|[^'\\\\\\n])*'`
    : lang === "js" ? "`(?:\\\\.|[^`\\\\])*`|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'"
    : "\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'";
  const re = new RegExp(`(${comment})|(${strings})|(\\b\\d[\\d_]*(?:\\.\\d+)?(?:e[+-]?\\d+)?\\b|\\b0x[0-9a-f]+\\b)|([A-Za-z_$][\\w$]*)(?=\\s*\\()|([A-Za-z_$][\\w$]*)`, "gi");
  const out: Token[] = [];
  let last = 0;
  const push = (k: TokenKind, v: string) => { const prev = out[out.length - 1]; if (prev && prev.k === k) prev.v += v; else out.push({ k, v }); };
  for (let m = re.exec(code); m; m = re.exec(code)) {
    if (m.index > last) push("plain", code.slice(last, m.index));
    const [whole, com, str, num, fn, word] = m;
    if (com) push("com", whole);
    else if (str) push("str", whole);
    else if (num) push("num", whole);
    else if (fn) push(kws.has(ci ? fn.toLowerCase() : fn) ? "kw" : "fn", whole);
    else if (word) push(kws.has(ci ? word.toLowerCase() : word) ? "kw" : /^[A-Z][a-z]/.test(word) && lang !== "sql" ? "type" : "plain", whole);
    last = m.index + whole.length;
  }
  if (last < code.length) push("plain", code.slice(last));
  return out;
}

export const TOKEN_CLASS: Record<TokenKind, string> = {
  kw: "text-[#ff6b75]", str: "text-[#9ece6a]", com: "text-[#5f6b7a] italic", num: "text-[#e0a63a]", fn: "text-[#7aa2f7]", type: "text-[#e5c07b]", plain: "",
};

/** A file path named on a code block ("python src/app.py") or in its first-line comment ("# file: src/app.py"). */
export function codeTarget(label: string, code: string): string | null {
  const fromLabel = label.trim().split(/\s+/).slice(1).join(" ") || (/[\w-]+\.[a-z0-9]{1,6}$/i.test(label.trim()) && !ALIAS[label.trim().toLowerCase()] ? label.trim() : "");
  const first = code.split("\n", 1)[0];
  const m = /^\s*(?:#|\/\/|--|\/\*)\s*(?:file|path)\s*:\s*([^\s*]+)/i.exec(first);
  const path = (fromLabel || m?.[1] || "").replace(/^\.\//, "");
  return path && !path.includes("..") && /^[\w./ -]+$/.test(path) ? path : null;
}
