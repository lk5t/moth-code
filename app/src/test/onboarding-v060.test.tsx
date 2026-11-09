import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Welcome, useWelcomeVisible, reopenWelcome } from "@/features/onboarding/Welcome";
import { appStore } from "@/lib/app-state";
vi.mock("@/lib/account", () => ({useAccount: (fn: (s:any) => unknown) => fn({ready:true,user:{username:"tester"},accounts:[]})}));
vi.mock("@/lib/connection", () => ({useConnection: (fn: (s:any) => unknown) => fn({status:"online"})}));
vi.mock("@/features/account/AccountDialog", () => ({openAccountDialog: vi.fn()}));
vi.mock("@/features/workspace/project-actions", () => ({pickProject: vi.fn()}));
function Introduction() {return useWelcomeVisible() ? <Welcome /> : <span>Workspace available</span>;}
afterEach(cleanup);
it("lets a beginner start chatting, then reopen and close the guide without losing the project", () => {
  appStore.setState({project:null});
  render(<Introduction />);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText(/find the active model/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Start chatting"}));
  expect(appStore.getState().view).toBe("chat");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  act(() => {appStore.setState({project:{id:1,name:"Existing project",path:"/project",last_opened:0}});reopenWelcome();});
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Close dialog"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(appStore.getState().project?.id).toBe(1);
  expect(localStorage.getItem("moth.welcome.done")).toBe("1");
});
