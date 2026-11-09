import {expect,it} from 'vitest';
import {observeNotices,activityNotices,dismissNotices,type ActivityEvent} from '@/lib/activity-notices';
const event=(id:string):ActivityEvent=>({id,ts:1,category:'deployment',action:'models.deployed',message:'Promoted',level:'info'});
it('baselines history, deduplicates refreshes/reconnects, and clears after reset/account changes',()=>{
 localStorage.clear();observeNotices('server|alice',0,[event('old')]);expect(activityNotices.getState().items).toHaveLength(0);
 observeNotices('server|alice',0,[event('new'),event('old')]);expect(activityNotices.getState().items).toHaveLength(1);
 observeNotices('server|alice',0,[event('new')]);expect(activityNotices.getState().items).toHaveLength(1);
 dismissNotices();observeNotices('server|alice',0,[event('new')]);expect(activityNotices.getState().items).toHaveLength(0);
 observeNotices('server|alice',1,[event('reset')]);expect(activityNotices.getState().items).toHaveLength(0);
 observeNotices('server|bob',1,[event('bob')]);expect(activityNotices.getState().items).toHaveLength(0);
 observeNotices('',0,[]);expect(activityNotices.getState().items).toHaveLength(0);
 expect(localStorage.getItem('moth.activity-seen')).not.toContain('Promoted');
});
