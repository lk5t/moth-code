import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
const mock=vi.hoisted(()=>({request:vi.fn()}));
vi.mock('@/lib/project-intelligence',()=>({projectApi:mock.request}));
vi.mock('@/features/agent/MemoryPanel',()=>({MemoryPanel:()=> <p>Legacy notes</p>}));
import { appStore } from '@/lib/app-state';
import { accountStore } from '@/lib/account';
import { ProjectIntelligencePanel } from '@/features/agent/ProjectIntelligencePanel';
beforeEach(()=>{
  mock.request.mockReset();appStore.setState({project:{id:1,name:'Demo',path:'/demo',last_opened:0}});
  accountStore.setState({token:'alice',serverUrl:'https://test'});
  mock.request.mockResolvedValue({summary:'3 analyzed files',frameworks:['React'],decisions:[]});
});
it('shows actual evidence, requires confirmed decisions, and confirms index deletion',async()=>{
  render(<ProjectIntelligencePanel/>);await screen.findByText('3 analyzed files');
  expect(screen.getByText('Framework evidence: React')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Decision'),{target:{value:'Use typed interfaces'}});
  expect(screen.getByText('Save decision')).toBeDisabled();
  fireEvent.click(screen.getByLabelText('I confirm this project decision'));
  fireEvent.click(screen.getByText('Save decision'));
  await waitFor(()=>expect(mock.request).toHaveBeenCalledWith('/api/projects/1/intelligence/decisions','POST',{text:'Use typed interfaces',confirmed:true}));
  vi.spyOn(window,'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByText('Delete index and memory'));
  expect(mock.request.mock.calls.some(call=>call[1]==='DELETE')).toBe(false);
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(screen.getByText('Delete index and memory'));
  await waitFor(()=>expect(mock.request).toHaveBeenCalledWith('/api/projects/1/intelligence','DELETE'));
});
it('hides old project analysis immediately on account change',async()=>{
  render(<ProjectIntelligencePanel/>);await screen.findByText('3 analyzed files');
  mock.request.mockImplementation(()=>new Promise(()=>{}));
  act(()=>accountStore.setState({token:'bob'}));
  expect(screen.queryByText('3 analyzed files')).toBeNull();
  expect(screen.getByRole('status')).toHaveTextContent('Analyzing');
});
