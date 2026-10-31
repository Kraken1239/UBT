"""Content consistency and independent arithmetic checks (not teacher review)."""
import json
import hashlib
from collections import Counter
from fractions import Fraction
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import server

class ContentTests(unittest.TestCase):
    def test_bank_schema_and_language_coverage(self):
        questions=server.validate_bank(json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8')))
        self.assertEqual(len(questions),250)
        for language in ['ru','kk','en']:
            for subject in server.SUBJECTS:
                selected=[q for q in questions if q['subject']==subject and q['language']==language]
                self.assertEqual(len(selected),5 if language=='en' else 10,(language,subject))
        for q in questions:
            for item in [q,q['recheck']]:
                self.assertEqual(len(item['options']),len(set(item['options'])),q['id'])
                self.assertNotEqual(q['prompt'],q['recheck']['prompt'],q['id'])

    def test_topic_coverage_and_bilingual_skills(self):
        questions=json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8'))
        for subject in server.SUBJECTS:
            grouped={lang:[q for q in questions if q['language']==lang and q['subject']==subject] for lang in ['ru','kk']}
            for lang,items in grouped.items():
                self.assertEqual(len({q['topic'] for q in items}),5,(subject,lang))
                self.assertEqual(sorted(Counter(q['skill_id'] for q in items).values()),[2]*5)
                prompts=[item['prompt'] for q in items for item in (q,q['recheck'])]
                self.assertEqual(len(prompts),len(set(prompts)))
            self.assertEqual(Counter(q['skill_id'] for q in grouped['ru']),Counter(q['skill_id'] for q in grouped['kk']))

    def test_english_bank_is_unchanged(self):
        questions=json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8'))
        english=[q for q in questions if q['language']=='en']
        digest=hashlib.sha256(json.dumps(english,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest,'2da4c6c827f6ae827f06401675c57b43d158c9ee21832db82f73bfec8dcb3f7f')

    def test_numeric_answer_keys_independently(self):
        questions=json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8'))
        tested=0
        for q in questions:
            if not q['id'].startswith('topics-v2-'):continue
            if q['subject'] not in {'math_lit','math_profile','physics','chemistry','informatics'}:continue
            for item in [q,q['recheck']]:
                selected=item['options'][item['correct_idx']]
                text=item['prompt'];subject=q['subject'];skill=q['skill_id'].split(':')[1]
                values=list(map(int,re.findall(r'\d+',text)))
                if skill=='quadratics':
                    total,product=values[:2];a,b=map(int,selected.split(';'))
                    self.assertEqual(a+b,total);self.assertEqual(a*b,product)
                elif skill=='logic':
                    x,lower,upper=values
                    self.assertEqual(selected,str(x>lower and x<upper))
                else:
                    if skill=='percentages':expected=Fraction(values[0]*(100-values[1]),100)
                    elif skill=='mean':expected=Fraction(sum(values),len(values))
                    elif skill=='ratio':expected=Fraction(values[1]*values[2],values[0]+values[1])
                    elif skill=='probability':expected=Fraction(values[0],sum(values))
                    elif skill=='work_rate':expected=Fraction(values[0],2)
                    elif skill=='linear':expected=Fraction(values[2]-values[1],values[0])
                    elif skill=='functions':expected=values[0]*values[2]**2-values[1]
                    elif skill=='geometry':expected=Fraction(values[0]*values[1],2)
                    elif skill=='powers':expected=values[0]**values[1]*values[2]**values[3]
                    elif skill=='speed':expected=Fraction(values[0],values[1]) if q['language']=='ru' else Fraction(values[1],values[0])
                    elif skill=='force':expected=values[0]*values[1]
                    elif skill=='voltage':expected=values[0]*values[1]
                    elif skill=='density':expected=Fraction(values[0],values[1])
                    elif skill=='work':expected=values[0]*values[1]
                    elif skill=='moles':expected=Fraction(values[1],values[0])
                    elif skill=='atomic_number':expected=values[0]
                    elif skill=='mass_conservation':expected=sum(values)
                    elif skill=='mass_fraction':expected=Fraction(values[1]*100,values[0])
                    elif skill=='neutrons':expected=values[0]-values[1]
                    elif skill=='binary':expected=int(str(values[0]),2)
                    elif skill=='bits':expected=values[0]*values[2] if q['language']=='ru' else values[1]*values[2]
                    elif skill=='variables':expected=values[0]+values[1]
                    elif skill=='loops':expected=values[1]*values[2]
                    else:self.fail(skill)
                    self.assertEqual(Fraction(selected),expected,(q['id'],text))
                tested+=1
        self.assertEqual(tested,200)

    def test_generator_reproduces_bank(self):
        import importlib.util
        import sys
        with patch.object(sys,'path',[str(server.ROOT/'scripts')]+sys.path):
            spec=importlib.util.spec_from_file_location('expand_demo',server.ROOT/'scripts/expand_demo.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            questions=json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8'))
            self.assertEqual(module.generate([q for q in questions if q['language']=='en']),questions)

    def test_explicit_utf8_when_default_encoding_differs(self):
        original=Path.read_text
        calls=[]
        def guarded(path,*args,**kwargs):
            calls.append(kwargs.get('encoding'))
            self.assertEqual(kwargs.get('encoding'),'utf-8')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',guarded):server.load_bank()
        self.assertTrue(calls)

if __name__=='__main__':unittest.main()

