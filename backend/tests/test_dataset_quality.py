import json
from moth.training.quality import inspect
from moth.training.sources import SourceSpec
from moth.training.data import prepare_dataset
from moth.model.tokenizer import Tokenizer
from moth.server.app import create_app
from fastapi.testclient import TestClient


def test_real_records_quality_preview_tokenization_and_consumption(tmp_path,tiny_pipeline):
    tok=tiny_pipeline['tokenizer'];path=tmp_path/'sample.jsonl';validation=tmp_path/'eval.jsonl'
    records=[{'prompt':'Explain addition','answer':'Add two values together.'},{'prompt':'Explain addition','answer':'Add two values together.'},{'text':'Held out example'}, {'messages':[{'role':'bogus','content':'wrong'}]}, {'text':'word '*30}]
    original='\n'.join(json.dumps(r) for r in records)+'\n{broken\n\n'
    path.write_text(original);validation.write_text(json.dumps({'text':'Held out example'})+'\n')
    src=SourceSpec('jsonl:'+str(path),'MIT');val=SourceSpec('jsonl:'+str(validation),'MIT')
    report=inspect([src],tok,[val])
    assert report['records']==4 and report['duplicates']==1 and report['validation_overlap']==1
    assert report['repetition_warnings']==1 and len(report['issues'])==3
    assert report['cleaning_preview']['retained']==2
    assert report['training_tokens']>0 and report['token_lengths']['max']>0
    assert path.read_text()==original
    cleaned=tmp_path/'derived.jsonl';cleaned.write_text('\n'.join(json.dumps(r) for r in report['cleaned_records'])+'\n')
    meta=prepare_dataset([SourceSpec('jsonl:'+str(cleaned),'MIT')],tok,tiny_pipeline['tokenizer_path'],tmp_path/'prepared',val_fraction=0.2)
    assert meta['tokens']['train']>0 and meta['tokens']['val']>0
    assert meta['tokenizer_fingerprint']==tok.fingerprint()


def test_quality_and_tokenizer_routes(paths,tiny_pipeline,tmp_path):
    path=tmp_path/'data.jsonl';path.write_bytes(b'{"text":"hello world"}\n\xff\n')
    tiny_pipeline['tokenizer'].save(paths.tokenizers/'test.json')
    app=create_app(paths,token='secret');headers={'Authorization':'Bearer secret'}
    with TestClient(app) as client:
        request={'tokenizer':'test','sources':[{'spec':'jsonl:'+str(path),'license':'MIT'}]}
        assert client.post('/api/datasets/quality',json=request).status_code==401
        response=client.post('/api/datasets/quality',headers=headers,json=request)
        assert response.status_code==200,response.text
        report=response.json();assert report['issues'] and 'cleaned_records' not in report
        sample=client.post('/api/tokenizers/preview',headers=headers,json={'tokenizer':'test','text':'hello world'}).json()
        assert sample['decoded']=='hello world' and sample['count']>0
        request['sources'][0]['license']=''
        assert client.post('/api/datasets/quality',headers=headers,json=request).status_code==422


def test_prepared_integrity_and_compatibility(paths,tiny_pipeline):
    import shutil
    shutil.copytree(tiny_pipeline['dataset'],paths.datasets/'prepared')
    tiny_pipeline['tokenizer'].save(paths.tokenizers/'matching.json')
    app=create_app(paths,token='secret');headers={'Authorization':'Bearer secret'}
    with TestClient(app) as client:
        endpoint='/api/datasets/prepared/quality'
        report=client.get(endpoint,headers=headers).json()
        assert report['tokenizer_available'] and report['actual_tokens']['train']>0
        with (paths.datasets/'prepared'/'train.mask').open('ab') as f:f.write(b'\x01')
        report=client.get(endpoint,headers=headers).json()
        assert any('sizes disagree' in issue for issue in report['issues'])
        assert report['status']=='needs_review'


def test_real_txt_and_near_duplicate_preview(tmp_path,tiny_pipeline):
    root=tmp_path/'txt';root.mkdir();(root/'notes.txt').write_text('A real UTF-8 training document with several words.\n')
    report=inspect([SourceSpec('dir:'+str(root),'MIT')],tiny_pipeline['tokenizer'])
    assert report['records']==1 and report['training_tokens']>0
    source=tmp_path/'near.jsonl'
    text='alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon'
    source.write_text(json.dumps({'text':text})+'\n'+json.dumps({'text':text+' omega'})+'\n')
    report=inspect([SourceSpec('jsonl:'+str(source),'MIT')],tiny_pipeline['tokenizer'])
    assert report['near_duplicates']==1 and report['cleaning_preview']['removed']==0
