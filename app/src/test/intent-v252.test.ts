import { describe, expect, it } from "vitest";
import { wantsAction } from "@/lib/intent";

describe("2.5.2 one chat: answer or act", () => {
  it("acts on clear requests to do something on the computer", () => {
    for (const m of ["run the tests", "Please open my downloads folder", "can you install requests",
      "create a README file for this project", "fix the bug in parser.py", "Rename notes.txt to todo.txt",
      "go to github.com and find my repos", "clean up my desktop"]) expect(wantsAction(m), m).toBe(true);
  });
  it("answers questions and plain writing requests", () => {
    for (const m of ["how do I run the tests?", "what is a closure", "explain this error", "write a function that adds two numbers",
      "make me a poem about moths", "fix this sentence: me and him goes", "hi", ""]) expect(wantsAction(m), m).toBe(false);
  });
});
