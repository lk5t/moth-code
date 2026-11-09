import {beforeEach,expect,it,vi} from 'vitest';
const mock=vi.hoisted(()=>({get:vi.fn(),put:vi.fn()}));
vi.mock('@/lib/backend',()=>mock);
vi.mock('@/lib/project-intelligence',()=>({projectApi:vi.fn(async()=>({}))}));
import {appStore} from '@/lib/app-state';
import {openFile,saveFile,refreshOpenFile,updateFile} from '@/features/workspace/workspace-actions';
beforeEach(()=>{mock.get.mockReset();mock.put.mockReset();appStore.setState({project:{id:1,name:'First',path:'/first',last_opened:0},openFiles:[{path:'a.py',content:'old',saved:'old',language:'python'}]});});
it('does not insert a late opened file into another project',async()=>{
 let resolve!:(v:any)=>void;mock.get.mockImplementation(()=>new Promise(r=>resolve=r));const opening=openFile('b.py');
 appStore.setState({project:{id:2,name:'Second',path:'/second',last_opened:0},openFiles:[]});resolve({content:'First project private content'});await opening;
 expect(appStore.getState().openFiles).toHaveLength(0);
});
it('marks only the content actually written as saved',async()=>{
 let resolve!:(v:any)=>void;mock.put.mockImplementation(()=>new Promise(r=>resolve=r));
 updateFile('a.py','submitted');const saving=saveFile('a.py');updateFile('a.py','new edits');resolve({});await saving;
 const file=appStore.getState().openFiles[0];expect(file.content).toBe('new edits');expect(file.saved).toBe('submitted');
});
it('keeps edits made while a disk refresh was in flight',async()=>{
 let resolve!:(v:any)=>void;mock.get.mockImplementation(()=>new Promise(r=>resolve=r));const refreshing=refreshOpenFile('a.py');
 updateFile('a.py','new edits');resolve({content:'disk update'});await refreshing;expect(appStore.getState().openFiles[0].content).toBe('new edits');
});
