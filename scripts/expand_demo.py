"""Rebuild five topics per RU/KK subject; preserve English records."""
import json
from pathlib import Path
from demo_topics import build_topics
ROOT=Path(__file__).resolve().parents[1]

def generate(english):
    items=list(english)
    for subject,skill,topics,rows in build_topics():
        for n,lang in enumerate(('ru','kk')):
            def unpack(row,offset):
                prompts,options,whys=row
                opts=options[n] if isinstance(options[0],list) else options
                shift=(offset+n)%len(opts)
                return dict(prompt=prompts[n],options=opts[shift:]+opts[:shift],correct_idx=(-shift)%len(opts),explanation=whys[n])
            for i in range(2):
                items.append(dict(unpack(rows[i],i),id=f'topics-v2-{subject}-{skill}-{i+1}-{lang}',subject=subject,language=lang,status='demo',skill_id=f'{subject}:{skill}',topic=topics[n],recheck=unpack(rows[i+2],i+2)))
    return items

if __name__=='__main__':
    path=ROOT/'content/demo.json'
    old=json.loads(path.read_text(encoding='utf-8'))
    items=generate([q for q in old if q['language']=='en'])
    path.write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(items)} questions')
