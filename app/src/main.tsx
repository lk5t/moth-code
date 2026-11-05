import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

window.addEventListener("contextmenu", (e) => {
  // Keep the native context menu only where it is useful (text inputs, editor).
  const t = e.target as HTMLElement;
  if (!t.closest("input, textarea, .monaco-editor, .selectable")) e.preventDefault();
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
