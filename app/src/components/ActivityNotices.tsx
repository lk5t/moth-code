import {useEffect} from 'react';
import {useCloudProgress} from '@/lib/cloud-progress';
import {useAccount} from '@/lib/account';
import {activityNotices,observeNotices,dismissNotices} from '@/lib/activity-notices';
import {navigate} from '@/lib/navigation';
export function ActivityNotices(){
 const {data}=useCloudProgress();const server=useAccount(s=>s.serverUrl),uid=useAccount(s=>s.user?.id),token=useAccount(s=>s.token);
 const scope=token ? server+'|'+uid : '';const state=activityNotices.useStore(s=>s);
 useEffect(()=>{if(!scope)observeNotices('',0,[]);else if(data?.activity)observeNotices(scope,data.activity.generation,data.activity.events);},[scope,data]);
 const notices=state.scope===scope?state.items:[];
 if(!notices.length)return null;
 return <div className="flex items-center justify-center gap-1 text-[10px] text-muted" role="status"><button onClick={()=>{dismissNotices();navigate('activity');}} className="rounded px-1 focus-visible:outline">{notices.length} new {notices.length===1?'event':'events'}</button><button aria-label="Dismiss activity notifications" onClick={dismissNotices}>×</button></div>;
}
