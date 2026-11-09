import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useResource } from "@/lib/hooks";
import { _testing } from "@/lib/events";

it("masks previous scope immediately and rejects late results across account changes", async () => {
  const pending: ((value: string) => void)[] = [];
  const loader = vi.fn(() => new Promise<string>(resolve => pending.push(resolve)));
  const {result, rerender, unmount} = renderHook(({scope}) => useResource('/private', ['files'], undefined, scope, loader), {initialProps:{scope:'alice'}});
  await act(async () => {pending[0]('Alice private');});
  expect(result.current.data).toBe('Alice private');
  act(() => {void result.current.reload();});
  rerender({scope:'bob'});
  expect(result.current.data).toBeUndefined();
  await act(async () => {pending[2]('Bob private'); pending[1]('Late Alice private');});
  expect(result.current.data).toBe('Bob private');
  unmount();
});
it("cleans event burst timers on unmount", async () => {
  const loader = vi.fn(async () => 'value');
  const {unmount} = renderHook(() => useResource('/project', ['files'], undefined, '', loader));
  await waitFor(() => expect(loader).toHaveBeenCalledTimes(1));
  act(() => _testing.dispatch({topic:'files',ts:1}));
  unmount();
  await new Promise(resolve => setTimeout(resolve,350));
  expect(loader).toHaveBeenCalledTimes(1);
});
