"""Content consistency and independent arithmetic checks (not teacher review)."""
import json
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

    def test_added_numeric_answer_keys_independently(self):
        questions=json.loads((server.ROOT/'content/demo.json').read_text(encoding='utf-8'))
        tested=0
        for q in questions:
            if not q['id'].startswith('extra-'):continue
            for item in [q,q['recheck']]:
                selected=item['options'][item['correct_idx']]
                text=item['prompt'];subject=q['subject']
                if subject=='math_lit':
                    price,rate=map(int,re.findall(r'\d+',text));self.assertEqual(int(selected),price*(100-rate)//100)
                elif subject=='math_profile':
                    match=re.search(r'x² − (\d+)x \+ (\d+)',text);total,product=map(int,match.groups());a,b=map(int,selected.split(';'))
                    self.assertEqual(a+b,total);self.assertEqual(a*b,product)
                elif subject=='physics':
                    first,second=map(int,re.findall(r'\d+',text));distance,duration=(first,second) if q['language']=='ru' else (second,first)
                    self.assertEqual(float(selected),distance/duration)
                elif subject=='chemistry':
                    molar,mass=map(int,re.findall(r'\d+',text));self.assertEqual(float(selected),mass/molar)
                elif subject=='informatics':
                    binary=re.search(r'\b[01]+\b',text)[0];self.assertEqual(int(selected),int(binary,2))
                else:continue
                tested+=1
        self.assertEqual(tested,180)

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

