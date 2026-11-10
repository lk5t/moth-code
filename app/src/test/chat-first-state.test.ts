import {expect,it,vi} from 'vitest';
it('starts a fresh installation in Chat and preserves existing saved workspace choices',async()=>{
 localStorage.clear();vi.resetModules();
 const first=await import('@/lib/app-state');expect(first.appStore.getState().view).toBe('chat');
 first.appStore.setState({view:'data',sidebarCollapsed:true});vi.resetModules();
 const restored=await import('@/lib/app-state');expect(restored.appStore.getState().view).toBe('data');expect(restored.appStore.getState().sidebarCollapsed).toBe(true);
});
