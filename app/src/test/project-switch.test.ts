import { beforeEach, expect, it, vi } from "vitest";
const mock=vi.hoisted(()=>({post:vi.fn(),get:vi.fn()}));
vi.mock("@/lib/backend",()=>({...mock,isTauri:()=>false}));
import { appStore } from "@/lib/app-state";
import { openProjectPath } from "@/features/workspace/project-actions";
beforeEach(()=>{mock.post.mockReset();appStore.setState({project:{id:1,name:"Current",path:"/current",last_opened:0},openFiles:[{path:"a.py",content:"unsaved",saved:"original",language:"python"}]});});
it("does not discard edits or authorize a different folder after cancelling",async()=>{
  vi.spyOn(window,"confirm").mockReturnValue(false);
  await openProjectPath('/different');expect(mock.post).not.toHaveBeenCalled();
  expect(appStore.getState().project?.id).toBe(1);expect(appStore.getState().openFiles[0].content).toBe("unsaved");
});
it("keeps unsaved files when reopening the same project",async()=>{
  mock.post.mockResolvedValue({id:1,name:"Current",path:"/current",last_opened:1});
  await openProjectPath('/current');expect(appStore.getState().openFiles[0].content).toBe("unsaved");
});
