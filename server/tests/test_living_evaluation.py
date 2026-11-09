import json
import pytest
from moth_server.evolution import evaluation as E, memory as MEM
from moth_server.intelligence import weakness


def test_consistency_and_all_unmeasured_capabilities(client):
    ctx=client.app.state.ctx
    missing=weakness.analyse(ctx,None)['not_measured']
    assert all(c in missing for c in ('conversation','knowledge','consistency','code','math','instruction','reasoning'))
    with pytest.raises(ValueError,match='paraphrase'):
        E.add_task_suite(ctx,'Consistency','consistency',b'{"prompt":"2+2?","answer":"4"}\n')
    suite=E.add_task_suite(ctx,'Consistency','consistency',b'{"prompt":"2+2?","paraphrase":"Sum two and two","answer":"4"}\n')
    MEM.save_report(ctx,1,'tasks:'+suite['id'],'suite-hash',{'ok':True,'value':0.5,'metric':'accuracy','higher_is_better':True,'capability':'consistency','n':2})
    report=weakness.analyse(ctx,1)
    assert 'consistency' not in report['not_measured']
    assert report['capabilities'][0]['capability']=='consistency'
