import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock=vi.hoisted(() => ({state:{token:"one",serverUrl:"https://cloud.test",user:{role:"owner"}},api:vi.fn()}));
vi.mock("@/lib/account", () => ({serverApi:mock.api,useAccount:(fn:(s:any)=>unknown)=>fn(mock.state)}));
import { useCloudProgress } from "@/lib/cloud-progress";
function Reader({id="reader"}:{id?:string}) {const state=useCloudProgress();return <p data-testid={id}>{state.data?.current?.name ?? "unavailable"}</p>;}
beforeEach(() => {mock.state.token="one";mock.api.mockReset();Object.defineProperty(document,"hidden",{configurable:true,value:false});});
afterEach(() => {cleanup();vi.useRealTimers();});
it("shares one progress request loop across consumers", async () => {
  vi.useFakeTimers();mock.api.mockResolvedValue({current:{name:"Actual model"}});
  await act(async () => {render(<><Reader id="one"/><Reader id="two"/></>);});
  expect(mock.api).toHaveBeenCalledTimes(1);expect(screen.getByTestId("two")).toHaveTextContent("Actual model");
  await act(async () => {await vi.advanceTimersByTimeAsync(5000);});
  expect(mock.api).toHaveBeenCalledTimes(2);
});
it("rejects a late previous-account response", async () => {
  let old!:(v:any)=>void, next!:(v:any)=>void;
  mock.api.mockImplementationOnce(() => new Promise((resolve)=>{old=resolve;})).mockImplementationOnce(() => new Promise((resolve)=>{next=resolve;}));
  const view=render(<Reader/>);mock.state.token="different-account";view.rerender(<Reader/>);
  await act(async () => {next({current:{name:"New account model"}});});
  await act(async () => {old({current:{name:"Old private model"}});});
  expect(screen.getByTestId("reader")).toHaveTextContent("New account model");expect(screen.queryByText("Old private model")).not.toBeInTheDocument();
});
it("waits while hidden, refreshes on visibility and clears after logout", async () => {
  Object.defineProperty(document,"hidden",{configurable:true,value:true});mock.api.mockResolvedValue({current:{name:"Loaded model"}});
  const view=render(<Reader/>);expect(mock.api).not.toHaveBeenCalled();
  Object.defineProperty(document,"hidden",{configurable:true,value:false});
  await act(async () => {document.dispatchEvent(new Event("visibilitychange"));});
  expect(screen.getByTestId("reader")).toHaveTextContent("Loaded model");
  mock.state.token="";view.rerender(<Reader/>);expect(screen.getByTestId("reader")).toHaveTextContent("unavailable");
});
