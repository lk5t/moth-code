/**
 * 2.5.2: one chat, like Claude — does this message ask MOTH to *do* something on the computer (open, run, change,
 * create files, use the web) or to answer? Questions and "how do I…" are answered; clear requests to act start a
 * task in the chat. Either way the other choice is one click away on the reply.
 */
const ALWAYS_ACT = /^(run|execute|install|uninstall|open|launch|start|stop|kill|delete|remove|rename|move|copy|download|upload|clone|commit|push|pull|deploy|organi[sz]e|clean up|tidy|set up|setup|go to|browse|visit|navigate to|click|log into|sign into|unzip|zip|extract|compress|back up|backup|restore|format|lint)\b/;
const ACT_WITH_OBJECT = /^(create|make|write|add|edit|change|update|fix|refactor|build|test|save|generate|put|append|replace|convert|resize|sort|merge|split|find|search|list|show me|look (through|in|at))\b/;
const PC_OBJECT = /\b(files?|folders?|director(y|ies)|repo(sitory)?|projects?|codebase|my code|desktop|documents|downloads|disk|drive|scripts?|readme|package\.json|requirements\.txt|tests?|website|web ?page|browser|tab|app|programs?|screenshot)\b|[~/\\]\S|[a-z]:\\|\.\w{1,5}\b/i;
const QUESTION = /^(how|what|why|when|where|which|who|is|are|does|do|did|should|would|explain|describe|tell me|teach|help me understand|what's|whats)\b/;
const POLITE = /^(please|pls|can you|could you|would you|will you|i want you to|i need you to|go ahead and|now|ok|okay|hey moth|moth)[,\s]+/;

export function wantsAction(message: string): boolean {
  let t = message.trim().toLowerCase();
  if (!t || t.length > 2000) return false;
  for (let i = 0; i < 3 && POLITE.test(t); i++) t = t.replace(POLITE, "");
  if (QUESTION.test(t)) return false;           // "how do I run the tests?" is a question
  if (ALWAYS_ACT.test(t)) return true;          // "run the tests", "open my downloads folder"
  return ACT_WITH_OBJECT.test(t) && PC_OBJECT.test(t);  // "create a README file", "fix the bug in parser.py"
}
