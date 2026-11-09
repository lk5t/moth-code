import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
const mock=vi.hoisted(()=>({post:vi.fn()}));
vi.mock('@/lib/backend',()=>mock);
vi.mock('@/features/training/SourcePicker',()=>({SourcePicker:({onChange}:any)=><button onClick={()=>onChange([{spec:'jsonl:/test',license:'MIT'}])}>Select test source</button>}));
import {DatasetQualityStudio} from '@/features/training/DatasetQualityStudio';
it('shows import evidence without claiming untested validation or altering originals',async()=>{
 mock.post.mockResolvedValue({records:2,training_tokens:40,status:'needs_review',duplicates:1,near_duplicates:0,repetition_warnings:0,validation_overlap:0,token_lengths:{min:20,max:20,mean:20},sources:[],issues:[{source:'data',record:3,message:'Malformed JSON'}],preview:[],cleaning_preview:{retained:1,removed:1,policy:'Originals intact'},limitations:[]});
 render(<DatasetQualityStudio tokenizers={[{name:'test',fingerprint:'fp'}]}/>);
 fireEvent.click(screen.getAllByText('Select test source')[0]);fireEvent.click(screen.getByText('Inspect quality and cleaning preview'));
 expect(await screen.findByText('2 examples · 40 estimated training tokens · needs review')).toBeTruthy();
 expect(screen.getByText(/Not tested — choose validation/)).toBeTruthy();expect(screen.getByText(/Malformed JSON/)).toBeTruthy();
 expect(mock.post).toHaveBeenCalledWith('/api/datasets/quality',{tokenizer:'test',sources:[{spec:'jsonl:/test',license:'MIT'}],validation_sources:[]});
});
