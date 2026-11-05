/** Bundle Monaco locally (no CDN) so the editor works fully offline. */
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/language/json/json.worker?worker";
import CssWorker from "monaco-editor/language/css/css.worker?worker";
import HtmlWorker from "monaco-editor/language/html/html.worker?worker";
import TsWorker from "monaco-editor/language/typescript/ts.worker?worker";

(self as any).MonacoEnvironment = {
  getWorker(_: string, label: string) {
    if (label === "json") return new JsonWorker();
    if (label === "css" || label === "scss" || label === "less") return new CssWorker();
    if (label === "html" || label === "handlebars" || label === "razor") return new HtmlWorker();
    if (label === "typescript" || label === "javascript") return new TsWorker();
    return new EditorWorker();
  },
};

monaco.editor.defineTheme("moth", {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "comment", foreground: "5f5f5f", fontStyle: "italic" },
    { token: "keyword", foreground: "ff4d5a" },
    { token: "string", foreground: "d7a9a9" },
    { token: "number", foreground: "f08c5a" },
    { token: "type", foreground: "e6e6e6", fontStyle: "bold" },
    { token: "function", foreground: "f2f2f2" },
  ],
  colors: {
    "editor.background": "#0b0b0b",
    "editor.foreground": "#e8e8e8",
    "editorLineNumber.foreground": "#3a3a3a",
    "editorLineNumber.activeForeground": "#C1121F",
    "editor.lineHighlightBackground": "#141414",
    "editor.selectionBackground": "#C1121F55",
    "editorCursor.foreground": "#ff3b47",
    "editorIndentGuide.background1": "#1d1d1d",
    "editorWidget.background": "#141414",
    "editorWidget.border": "#262626",
    "scrollbarSlider.background": "#2a2a2a88",
    "minimap.background": "#0b0b0b",
  },
});

loader.config({ monaco });
export { monaco };
