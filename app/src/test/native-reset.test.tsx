import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
const mock=vi.hoisted(()=>({api:vi.fn(),state:{token:'owner',serverUrl:'https://isolated.test',user:{role:'owner'}}}));
vi.mock('@/lib/account',()=>({serverApi:mock.api,useAccount:(fn:any)=>fn(mock.state)}));
vi.mock('@/features/owner/ops',()=>({secure:(fn:any)=>fn(),formatBytes:(n:number)=>n+' bytes'}));
vi.mock('@/lib/cloud-progress',()=>({refreshCloudProgress:vi.fn()}));
import {NativeResetPanel} from '@/features/intelligence/NativeResetPanel';
it('requires a preview and separate exact deletion confirmations',async()=>{
 let plan:any={status:'idle'};
 mock.api.mockImplementation((path:string)=>{if(path.endsWith('/preview'))plan={id:'isolated-reset',status:'preview',backups:true,inventory:{roots:[{category:'lineage',files:2,bytes:10}],records:{model_releases:2},managed_backup_files:1,external_references:[],disclosure:'Fixture only'}};return Promise.resolve(plan);});
 render(<NativeResetPanel/>);
 expect(screen.queryByText('Permanently delete reviewed native AI data')).toBeNull();
 fireEvent.click(screen.getByLabelText(/Include managed GENESIS/));
 fireEvent.click(screen.getByText('Inspect deletion inventory'));
 const execute=await screen.findByText('Permanently delete reviewed native AI data');expect(execute).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Confirm all native AI deletion'),{target:{value:'DELETE ALL NATIVE AI DATA'}});expect(execute).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Confirm managed AI backup deletion'),{target:{value:'DELETE MANAGED AI BACKUPS'}});
 fireEvent.click(execute);
 await waitFor(()=>expect(mock.api).toHaveBeenCalledWith('/v1/admin/evolution/native-reset/execute',expect.objectContaining({json:{reset_id:'isolated-reset',confirmation:'DELETE ALL NATIVE AI DATA',backup_confirmation:'DELETE MANAGED AI BACKUPS'}})));
});

it('does not expose an old Owner operation response after switching deployment',async()=>{
 let reject!:(error:Error)=>void;
 mock.state={token:'owner',serverUrl:'https://isolated.test',user:{role:'owner'}};
 const preview={id:'isolated-reset',status:'preview',backups:false,inventory:{roots:[],records:{},managed_backup_files:0,external_references:[],disclosure:'Fixture'}};
 mock.api.mockImplementation((path:string)=>path.endsWith('/execute')?new Promise((_,fail)=>{reject=fail;}):Promise.resolve(mock.state.token==='owner'?preview:{status:'idle'}));
 const view=render(<NativeResetPanel/>);
 await screen.findByText('Permanently delete reviewed native AI data');
 fireEvent.change(screen.getByLabelText('Confirm all native AI deletion'),{target:{value:'DELETE ALL NATIVE AI DATA'}});
 fireEvent.click(screen.getByText('Permanently delete reviewed native AI data'));
 await waitFor(()=>expect(reject).toBeTypeOf('function'));
 mock.state={token:'different-owner',serverUrl:'https://other-deployment.test',user:{role:'owner'}};
 view.rerender(<NativeResetPanel/>);
 await act(async()=>{reject(new Error('Private error from the old deployment'));});
 expect(screen.queryByText('Private error from the old deployment')).toBeNull();
 expect(screen.queryByLabelText('Confirm all native AI deletion')).toBeNull();
});
