"""Bounded, read-only dataset inspection and non-destructive cleaning previews."""
from __future__ import annotations
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from moth.model.chat_format import Message, encode_chat
from moth.training.sources import SourceSpec, Document, iter_source, resolve_license

MAX_RECORDS=1000
MAX_BYTES=8*1024*1024


def _record(row, source, number):
    if not isinstance(row,dict):raise ValueError('Expected a JSON object')
    messages=row.get('messages')
    if messages is None and ('prompt' in row or 'answer' in row):
        if not all(isinstance(row.get(k),str) and row[k].strip() for k in ('prompt','answer')):raise ValueError('Prompt and answer must be non-empty text')
        messages=[{'role':'user','content':row['prompt']},{'role':'assistant','content':row['answer']}]
    if messages is not None:
        if not isinstance(messages,list) or not messages:raise ValueError('Messages must be a non-empty list')
        previous=None;seen_user=False
        for item in messages:
            if not isinstance(item,dict) or item.get('role') not in ('system','user','assistant','tool','tool_call','tool_result') or not isinstance(item.get('content'),str) or not item['content'].strip():raise ValueError('Invalid conversation role or empty content')
            role=item['role']
            if role=='system' and previous is not None:raise ValueError('System message must come first')
            if role=='user':seen_user=True
            if role=='assistant' and not seen_user:raise ValueError('Assistant answer needs a preceding user message')
            if role==previous and role in ('user','assistant'):raise ValueError('Repeated conversation role')
            previous=role
        if not any(item['role']=='assistant' for item in messages):raise ValueError('No assistant training answer')
        messages=[{'role':'tool_result' if m['role']=='tool' else m['role'],'content':m['content']} for m in messages]
        return Document('\n'.join(m['content'] for m in messages),source,str(number),messages=messages)
    if not isinstance(row.get('text'),str) or not row['text'].strip():raise ValueError('Expected non-empty text, prompt/answer or messages')
    return Document(row['text'],source,str(number))


def inspect(sources, tokenizer, validation_sources=()):
    issues=[];records=[];total_bytes=0;truncated=False;provenance=[];scanned=0
    def documents(spec):
        nonlocal total_bytes,truncated,scanned
        resolve_license(spec)
        if spec.kind=='jsonl':
            path=Path(spec.target)
            with path.open('rb') as stream:
                number=0
                while line := stream.readline(MAX_BYTES+1):
                    number+=1
                    scanned+=1;total_bytes+=len(line)
                    if scanned>MAX_RECORDS or total_bytes>MAX_BYTES:truncated=True;break
                    if not line.strip():issues.append({'source':spec.spec,'record':number,'kind':'empty','message':'Empty line'});continue
                    try:yield _record(json.loads(line.decode('utf-8-sig')),spec.spec,number)
                    except (UnicodeError,ValueError) as error:issues.append({'source':spec.spec,'record':number,'kind':'invalid','message':str(error)[:200]})
        else:
            limited=SourceSpec(spec.spec,spec.license,min(MAX_RECORDS,spec.max_documents or MAX_RECORDS),min(MAX_BYTES,spec.max_bytes or MAX_BYTES),spec.options)
            for doc in iter_source(limited):
                scanned+=1;total_bytes+=len(doc.text.encode('utf-8'))
                if scanned>MAX_RECORDS or total_bytes>MAX_BYTES:truncated=True;break
                yield doc
            if scanned>=MAX_RECORDS:truncated=True
    validation=set()
    for src in validation_sources:
        spec=SourceSpec.from_any(src)
        for doc in documents(spec):validation.add(_digest(doc))
    seen=set();buckets=defaultdict(list);duplicates=near=contamination=repetition=0;lengths=[];preview=[];clean=[]
    for src in sources:
        spec=SourceSpec.from_any(src);lic=resolve_license(spec)
        path=Path(spec.target) if spec.kind in ('dir','jsonl') else None
        provenance.append({'source':spec.spec,'license':lic,'format':spec.kind,'bytes':path.stat().st_size if path and path.is_file() else None})
        for doc in documents(spec):
            digest=_digest(doc);duplicate=digest in seen;seen.add(digest)
            if duplicate:duplicates+=1
            leaked=digest in validation;contamination+=leaked
            words=re.findall(r'\w+',doc.text.lower());grams=set(zip(words,words[1:],words[2:]))
            key=words[0] if words else ''
            almost=not duplicate and len(grams)>4 and any(len(grams & prior)/max(1,len(grams | prior))>=0.85 for prior in buckets[key][-100:])
            if almost:near+=1
            if grams:buckets[key].append(grams)
            repeated=len(words)>=20 and len(set(words))/len(words)<0.2;repetition+=repeated
            if doc.messages:ids,mask=encode_chat(tokenizer,[Message(m['role'],m['content']) for m in doc.messages],add_generation_prompt=False)
            else:ids=tokenizer.encode(doc.text)
            lengths.append(len(ids)+1)
            row={'messages':doc.messages} if doc.messages else {'text':doc.text}
            if not duplicate and not leaked:clean.append(row)
            if len(preview)<5:preview.append({'source':doc.source,'record':doc.id,'text':doc.text[:500],'tokens':len(ids)+1,'duplicate':duplicate,'near_duplicate':almost,'validation_overlap':leaked,'repetition':repeated})
        if truncated:break
    clean_bytes=json.dumps(clean,ensure_ascii=False).encode()
    return {'sources':provenance,'records':len(lengths),'scanned_records':scanned,'training_tokens':sum(lengths),'tokenizer_fingerprint':tokenizer.fingerprint(),
        'status':'needs_review' if issues or duplicates or near or contamination or repetition or truncated else 'checked_sample',
        'duplicates':duplicates,'near_duplicates':near,'validation_overlap':contamination,'repetition_warnings':repetition,'issues':issues[:100],
        'token_lengths':{'min':min(lengths,default=0),'max':max(lengths,default=0),'mean':round(sum(lengths)/max(1,len(lengths)),1)},
        'truncated':truncated,'sample_limit':MAX_RECORDS,'preview':preview,'cleaning_preview':{'retained':len(clean),'removed':len(lengths)-len(clean),'policy':'Remove exact duplicates and exact validation overlaps only; malformed records are excluded. Near duplicates/repetition require review.'},
        'cleaned_records':clean,'inspection_sha256':hashlib.sha256(clean_bytes).hexdigest(),
        'limitations':['Bounded inspection; results do not certify the entire dataset.','Near-duplicate detection uses word trigrams within first-word buckets.','Validation overlap checks exact records against explicitly selected validation sources.','Token counts are inspection estimates; prepared metadata is authoritative.']}


def _digest(doc):
    value=json.dumps(doc.messages,sort_keys=True,ensure_ascii=False) if doc.messages else doc.text
    return hashlib.sha256(value.strip().encode()).hexdigest()
