import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup} from '@testing-library/react';
const mock=vi.hoisted(()=>({api:vi.fn(),local:vi.fn(),localReset:vi.fn(),state:{token:'owner',serverUrl:'https://isolated.test',user:{role:'owner'}}}));
vi.mock('@/lib/account',()=>({serverApi:mock.api,useAccount:(fn:any)=>fn(mock.state)}));
vi.mock('@/lib/backend',()=>({get:mock.local,post:mock.localReset}));
vi.mock('@/features/owner/ops',()=>({secure:(fn:any)=>fn(),formatBytes:(n:number)=>n+' bytes'}));
vi.mock('@/lib/cloud-progress',()=>({refreshCloudProgress:vi.fn()}));
import {NativeResetPanel} from '@/features/intelligence/NativeResetPanel';
afterEach(()=>{cleanup();vi.clearAllMocks();});
const inventory={roots:[{category:'lineage',files:2,bytes:10}],records:{model_releases:2},managed_backup_files:1,external_references:[],disclosure:'Fixture only'};

it('needs a review, the typed phrase and a final confirmation before anything is sent',async()=>{
 let plan:any={status:'idle',confirmation:'RESET GENESIS'};
 mock.local.mockResolvedValue({files:3,bytes:30,running_jobs:[]});mock.localReset.mockResolvedValue({deleted_files:3,deleted_bytes:30});
 mock.api.mockImplementation((path:string)=>{
  if(path.endsWith('/preview'))plan={id:'isolated-reset',status:'preview',confirmation:'RESET GENESIS',backups:true,inventory};
  if(path.endsWith('/execute'))plan={id:'isolated-reset',status:'completed',ready_for_genesis:true,retained_managed_backup_files:0,retained_external_copies:0,disclosure:'Fixture only'};
  return Promise.resolve(plan);});
 render(<NativeResetPanel/>);
 expect(screen.queryByLabelText('Genesis Reset confirmation')).toBeNull();  // nothing to type before the review
 fireEvent.click(screen.getByLabelText(/Also delete managed GENESIS/));
 fireEvent.click(screen.getByText('Review deletion'));
 const next=await screen.findByText('Continue to final confirmation');expect(next).toBeDisabled();
 expect(screen.getByText(/2 files \(10 bytes\) and 2 records will be deleted/)).toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Genesis Reset confirmation'),{target:{value:'reset genesis'}});expect(next).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Genesis Reset confirmation'),{target:{value:'RESET GENESIS'}});expect(next).toBeDisabled();  // backups need their own phrase
 fireEvent.change(screen.getByLabelText('Managed backup deletion confirmation'),{target:{value:'DELETE MANAGED AI BACKUPS'}});
 fireEvent.click(screen.getByLabelText(/Also delete native AI data on this computer/));
 fireEvent.click(next);
 expect(mock.api).not.toHaveBeenCalledWith(expect.stringMatching(/execute$/),expect.anything());  // still nothing sent
 fireEvent.click(await screen.findByText('Delete everything and reset'));
 await waitFor(()=>expect(mock.api).toHaveBeenCalledWith('/v1/admin/evolution/native-reset/execute',expect.objectContaining({json:{reset_id:'isolated-reset',confirmation:'RESET GENESIS',backup_confirmation:'DELETE MANAGED AI BACKUPS'}})));
 await screen.findByText('No Model — Ready for Genesis');
 expect(mock.localReset).toHaveBeenCalledWith('/api/native-ai/reset',{confirmation:'RESET GENESIS'});
 expect(screen.getByText('Begin Genesis')).toBeInTheDocument();
});

it('cancelling the final confirmation deletes nothing',async()=>{
 const plan={id:'r',status:'preview',confirmation:'RESET GENESIS',backups:false,inventory};
 mock.local.mockResolvedValue({files:0,bytes:0});mock.api.mockResolvedValue(plan);
 render(<NativeResetPanel/>);
 fireEvent.change(await screen.findByLabelText('Genesis Reset confirmation'),{target:{value:'RESET GENESIS'}});
 fireEvent.click(screen.getByText('Continue to final confirmation'));
 fireEvent.click(await screen.findByText('Cancel'));
 expect(mock.api).not.toHaveBeenCalledWith(expect.stringMatching(/execute$/),expect.anything());
});

it('sends the phrase a MOTH Cloud 0.6.0 expects while the Owner types RESET GENESIS',async()=>{
 const plan={id:'old',status:'preview',backups:false,inventory};  // 0.6.0 status has no confirmation field
 mock.local.mockResolvedValue({files:0,bytes:0});mock.api.mockResolvedValue(plan);
 render(<NativeResetPanel/>);
 fireEvent.change(await screen.findByLabelText('Genesis Reset confirmation'),{target:{value:'RESET GENESIS'}});
 fireEvent.click(screen.getByText('Continue to final confirmation'));
 fireEvent.click(await screen.findByText('Delete everything and reset'));
 await waitFor(()=>expect(mock.api).toHaveBeenCalledWith('/v1/admin/evolution/native-reset/execute',expect.objectContaining({json:expect.objectContaining({confirmation:'DELETE ALL NATIVE AI DATA'})})));
});

it('does not expose an old Owner operation response after switching deployment',async()=>{
 let reject!:(error:Error)=>void;
 mock.state={token:'owner',serverUrl:'https://isolated.test',user:{role:'owner'}};
 mock.local.mockResolvedValue({files:0,bytes:0});
 const preview={id:'isolated-reset',status:'preview',confirmation:'RESET GENESIS',backups:false,inventory:{roots:[],records:{},managed_backup_files:0,external_references:[],disclosure:'Fixture'}};
 mock.api.mockImplementation((path:string)=>path.endsWith('/execute')?new Promise((_,fail)=>{reject=fail;}):Promise.resolve(mock.state.token==='owner'?preview:{status:'idle'}));
 const view=render(<NativeResetPanel/>);
 fireEvent.change(await screen.findByLabelText('Genesis Reset confirmation'),{target:{value:'RESET GENESIS'}});
 fireEvent.click(screen.getByText('Continue to final confirmation'));
 fireEvent.click(await screen.findByText('Delete everything and reset'));
 await waitFor(()=>expect(reject).toBeTypeOf('function'));
 mock.state={token:'different-owner',serverUrl:'https://other-deployment.test',user:{role:'owner'}};
 view.rerender(<NativeResetPanel/>);
 await act(async()=>{reject(new Error('Private error from the old deployment'));});
 expect(screen.queryByText('Private error from the old deployment')).toBeNull();
 expect(screen.queryByLabelText('Genesis Reset confirmation')).toBeNull();
});

it('is not rendered for a non-Owner',()=>{
 mock.state={token:'user',serverUrl:'https://isolated.test',user:{role:'user'}};
 const {container}=render(<NativeResetPanel/>);
 expect(container).toBeEmptyDOMElement();expect(mock.api).not.toHaveBeenCalled();
 mock.state={token:'owner',serverUrl:'https://isolated.test',user:{role:'owner'}};
});
