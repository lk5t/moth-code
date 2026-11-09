import {createStore} from './store';
export type ActivityEvent={id:string;ts:number;category:string;message:string;level:string;action:string};
export const activityNotices=createStore({scope:'',generation:0,items:[] as ActivityEvent[]});
let initialized=false,seen=new Set<string>();
const important=(event:ActivityEvent)=>event.level==='error' || /^(models\.deployed|models\.rollback|evolution\.rollback|native_reset\.completed|updates\..*|software\..*|experiment\.rejected|cycle\.failed)$/.test(event.action);
export function observeNotices(scope:string,generation:number,events:ActivityEvent[]){
 const state=activityNotices.getState();
 if(state.scope!==scope || state.generation!==generation){
  seen=new Set();initialized=false;activityNotices.setState({scope,generation,items:[]});
  if(scope)try{const data=JSON.parse(localStorage.getItem('moth.activity-seen')||'{}');if(data.scope===scope && data.generation===generation){seen=new Set(data.ids);initialized=true;}}catch{/* optional local metadata */}
 }
 if(!scope)return;
 const incoming=events.filter(event=>!seen.has(event.id)&&important(event));
 events.forEach(event=>seen.add(event.id));
 if(initialized&&incoming.length)activityNotices.setState({items:[...incoming,...activityNotices.getState().items].filter((event,index,all)=>all.findIndex(other=>other.id===event.id)===index).slice(0,10)});
 initialized=true;seen=new Set([...seen].slice(-500));
 try{localStorage.setItem('moth.activity-seen',JSON.stringify({scope,generation,ids:[...seen]}));}catch{/* optional metadata; never store event contents or credentials */}
}
export function dismissNotices(){activityNotices.setState({items:[]});}
