import concurrent.futures
import http.cookiejar
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import server

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        server.DATA=Path(cls.temp.name)
        server.initialize()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.http.daemon_threads=True
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()

    def setUp(self):
        server.LIMITS.clear()
        self.client=self.new_client()
        self.email='student-'+os.urandom(6).hex()+'@example.com'
        code,_=self.request('/api/register','POST',{'email':self.email,'password':'Long-password-123','language':'ru'},self.client)
        self.assertEqual(code,200)

    def new_client(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self,path,method='GET',body=None,client=None,headers=None):
        h={'Content-Type':'application/json','X-UBT-Request':'1'}
        if headers:h.update(headers)
        req=urllib.request.Request(self.base+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with (client or self.client).open(req,timeout=10) as r:
                raw=r.read();return r.status,json.loads(raw) if 'application/json' in r.headers['Content-Type'] else raw
        except urllib.error.HTTPError as e:return e.code,json.load(e)

    def attempt(self):
        status,a=self.request('/api/attempts','POST',{'subject':'math_lit'})
        self.assertEqual(status,201)
        self.assertTrue(a['questions'])
        return a

    def completed(self):
        a=self.attempt()
        status,r=self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':[None]*len(a['questions'])})
        self.assertEqual(status,200)
        return a,r

    def test_static_and_no_private_files(self):
        self.assertEqual(self.request('/')[0],200)
        for path in ['/server.py','/.data/ubt.sqlite3','/content/demo.json','/../server.py']:
            self.assertNotEqual(self.request(path)[0],200)
        self.assertEqual(self.request('/api/health')[1],{'ok':True})

    def test_session_cookie_and_password_hash(self):
        self.assertEqual(self.request('/api/me')[1]['email'],self.email)
        with server.database() as db:
            password=db.execute('SELECT password FROM users WHERE email=?',(self.email,)).fetchone()[0]
            token=db.execute('SELECT token FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)',(self.email,)).fetchone()[0]
        self.assertNotIn('Long-password',password)
        self.assertEqual(len(token),64)
        self.assertIn('HttpOnly',server.Handler.session_cookie(server.Handler,'x'))
        self.assertIn('SameSite=Lax',server.Handler.session_cookie(server.Handler,'x'))

    def test_login_and_second_device_sync(self):
        self.completed()
        second=self.new_client()
        self.assertEqual(self.request('/api/login','POST',{'email':self.email,'password':'wrong-password'},second)[0],401)
        self.assertEqual(self.request('/api/login','POST',{'email':self.email,'password':'Long-password-123'},second)[0],200)
        self.assertEqual(len(self.request('/api/progress',client=second)[1]['history']),1)
        self.request('/api/logout','POST',{},second)
        self.assertEqual(self.request('/api/me',client=second)[0],401)
        self.assertEqual(self.request('/api/me')[0],200)

    def test_cross_account_isolation(self):
        a,_=self.completed()
        second=self.new_client()
        self.request('/api/register','POST',{'email':'other-'+self.email,'password':'Long-password-123'},second)
        self.assertEqual(self.request('/api/progress',client=second)[1]['history'],[])
        self.assertEqual(self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':[0]*len(a['questions'])},second)[0],404)
        self.assertEqual(self.request('/api/review','POST',{'attemptId':a['id'],'questionId':a['questions'][0]['id']},second)[0],404)

    def test_grading_and_idempotency(self):
        a=self.attempt()
        self.assertNotIn('correct_idx',a['questions'][0])
        self.assertNotIn('explanation',a['questions'][0])
        self.assertNotIn('recheck',a['questions'][0])
        correct=[server.BANK[q['id']]['correct_idx'] for q in a['questions']]
        s,r=self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':correct})
        self.assertEqual(r['score'],r['total'])
        again=self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':[None]*len(correct)})[1]
        self.assertEqual(again,r)
        self.assertEqual(len(self.request('/api/progress')[1]['history']),1)

    def practice(self,payload,new=False):
        status,data=self.request('/api/practice/new' if new else '/api/review','POST',payload)
        self.assertEqual(status,200)
        practice=data['practice']
        with server.database() as db:
            item=json.loads(db.execute('SELECT item FROM practice WHERE id=?',(practice['id'],)).fetchone()[0])
        return practice,item

    def test_wrong_then_correct_without_leaving_review(self):
        a,r=self.completed();q=r['questions'][0];payload={'attemptId':a['id'],'questionId':q['id']}
        p,item=self.practice(payload)
        self.assertNotIn('correct_idx',p)
        wrong=(item['correct_idx']+1)%len(item['options'])
        request=dict(payload,practiceId=p['id'],answer=wrong)
        first=self.request('/api/recheck','POST',request)[1]
        self.assertFalse(first['correct'])
        # Double submission does not overwrite the original wrong answer.
        again=self.request('/api/recheck','POST',dict(request,answer=item['correct_idx']))[1]
        self.assertEqual(first,again)
        reopened,_=self.practice(payload)
        self.assertEqual(reopened['result'],first)
        p2,item2=self.practice(payload,new=True)
        self.assertNotEqual(p['id'],p2['id'])
        self.assertNotEqual(item['prompt'],item2['prompt'])
        correct=self.request('/api/recheck','POST',dict(payload,practiceId=p2['id'],answer=item2['correct_idx']))[1]
        self.assertTrue(correct['correct'])
        skills=self.request('/api/progress')[1]['skills']
        self.assertTrue(any(s['status']=='initial_understanding' for s in skills))
        with server.database() as db:
            count=db.execute('SELECT count(*) FROM checks WHERE question_id=? AND user_id=(SELECT id FROM users WHERE email=?)',(q['id'],self.email)).fetchone()[0]
        self.assertEqual(count,2)

    def test_practice_ownership_and_concurrent_next(self):
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id']}
        p,item=self.practice(payload)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.request('/api/practice/new','POST',payload),range(2)))
        self.assertEqual(results[0][1]['practice']['id'],p['id'])
        self.assertEqual(results[1][1]['practice']['id'],p['id'])
        other=self.new_client()
        self.request('/api/register','POST',{'email':'practice-'+self.email,'password':'Long-password-123'},other)
        self.assertEqual(self.request('/api/recheck','POST',dict(payload,practiceId=p['id'],answer=0),other)[0],404)
        self.assertEqual(self.request('/api/recheck','POST',dict(payload,practiceId='fake',answer=0))[0],404)

    def test_wrong_check_does_not_mark_understanding(self):
        a,r=self.completed();q=r['questions'][0];payload={'attemptId':a['id'],'questionId':q['id']}
        p,item=self.practice(payload)
        answer=(item['correct_idx']+1)%len(item['options'])
        _,r=self.request('/api/recheck','POST',dict(payload,practiceId=p['id'],answer=answer))
        self.assertFalse(r['correct'])
        self.assertTrue(all(s['status']=='needs_practice' for s in self.request('/api/progress')[1]['skills']))

    def test_exhausted_variants_remain_practicable(self):
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id']}
        seen=set();repeated=False
        for _ in range(12):
            p,item=self.practice(payload,new=True)
            status,result=self.request('/api/recheck','POST',dict(payload,practiceId=p['id'],answer=item['correct_idx']))
            self.assertEqual(status,200)
            repeated=repeated or result['repeated']
            seen.add(item['prompt'])
        self.assertGreater(len(seen),1)
        self.assertTrue(repeated)
        statuses={s['status'] for s in self.request('/api/progress')[1]['skills']}
        self.assertNotIn('delayed_repeat_passed',statuses)

    def test_ai_fallback_and_reasoning_validation(self):
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id']}
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.request('/api/agent','POST',dict(payload,reasoning='x'))[0],400)
            response=self.request('/api/agent','POST',dict(payload,reasoning='Я умножил число на 25 и не разделил на сто'))[1]
        self.assertEqual(response['mode'],'prepared')
        self.assertTrue(response['response'])

    def test_ai_adapter_mock_and_failure(self):
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id'],'reasoning':'Сначала я выполнил умножение'}
        original=urllib.request.urlopen
        class Fake:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'choices':[{'message':{'content':'Проверь перевод процентов в долю.'}}]}).encode()
        with patch.dict(os.environ,{'UBT_AI_API_KEY':'test-only-not-a-real-key'}),patch.object(server.urllib.request,'urlopen',return_value=Fake()) as call:
            response=self.request('/api/agent','POST',payload)[1]
            self.assertEqual(response['mode'],'ai')
            req=call.call_args[0][0]
            sent=json.loads(req.data)
            self.assertIn(payload['reasoning'],sent['messages'][1]['content'])
            self.assertNotIn('recheck',sent['messages'][1]['content'])
            self.request('/api/agent','POST',dict(payload,reasoning='Почему здесь нужно делить на сто?'))
            messages=json.loads(call.call_args[0][0].data)['messages']
            self.assertEqual(len(messages),4)
            self.assertEqual(messages[2]['role'],'assistant')
            conversation=self.request('/api/review','POST',payload)[1]['conversation']
            self.assertEqual(len(conversation),2)
        with patch.dict(os.environ,{'UBT_AI_API_KEY':'test-only-not-a-real-key'}),patch.object(server.urllib.request,'urlopen',side_effect=urllib.error.URLError('offline')):
            self.assertEqual(self.request('/api/agent','POST',payload)[0],502)

    def test_csrf_invalid_input_and_expiry(self):
        self.assertEqual(self.request('/api/logout','POST',{},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/logout','POST',{},headers={'X-UBT-Request':''})[0],403)
        a=self.attempt()
        self.assertEqual(self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':[999]*len(a['questions'])})[0],400)
        with server.database() as db:db.execute('UPDATE attempts SET created=created-400 WHERE id=?',(a['id'],))
        r=self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':[0]*len(a['questions'])})[1]
        self.assertTrue(r['expired']);self.assertEqual(r['score'],0)

    def test_languages_and_profile_persistence(self):
        for language in ['ru','kk','en']:
            p={'name':'<script>bad()</script>','grade':'10','language':language,'profilePair':'Biology-Chemistry'}
            self.assertEqual(self.request('/api/profile','PUT',{'profile':p})[0],200)
            self.assertEqual(self.request('/api/me')[1]['profile'],p)
            cat=self.request('/api/catalog')[1]
            self.assertEqual(len(cat),5)
            self.assertTrue(all(s['count']>0 for s in cat))
            a=self.request('/api/attempts','POST',{'subject':'biology'})[1]
            self.assertEqual(a['questions'][0]['language'],language)
        self.assertEqual(self.request('/api/attempts','POST',{'subject':'physics'})[0],400)

    def test_bank_validation(self):
        import copy
        bank=copy.deepcopy(list(server.BANK.values())[:1])
        self.assertEqual(len(server.validate_bank(bank)),1)
        bank[0]['status']='reviewed'
        with self.assertRaises(server.Problem):server.validate_bank(bank)
        bank[0].update(source='https://example.org/authorized-bank',license='Permission recorded by operator',reviewed_by='Teacher',reviewed_at='2026-01-01')
        server.validate_bank(bank)
        bank[0]['correct_idx']=99
        with self.assertRaises(server.Problem):server.validate_bank(bank)

    def test_concurrent_submissions_are_idempotent(self):
        a=self.attempt()
        path='/api/attempts/'+a['id']+'/submit'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.request(path,'POST',{'answers':[None]*len(a['questions'])}),range(2)))
        self.assertTrue(all(status==200 for status,_ in results))
        self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(len(self.request('/api/progress')[1]['history']),1)

    def test_import_cli_and_reviewed_selection(self):
        import copy
        import subprocess
        q=copy.deepcopy(next(q for q in server.BANK.values() if q['subject']=='math_lit' and q['language']=='ru'))
        q.update(id='reviewed-test-import',status='reviewed',source='https://example.org/licensed-example',license='Test fixture only',reviewed_by='Test reviewer',reviewed_at='2026-01-01')
        source=server.DATA/'fixture.json';source.write_text(json.dumps([q]),encoding='utf-8')
        environment=dict(os.environ,UBT_DATA_DIR=str(server.DATA))
        def command(name):
            return subprocess.run([sys.executable,str(server.ROOT/'server.py'),name,str(source)],env=environment,capture_output=True,text=True)
        try:
            self.assertEqual(command('validate-bank').returncode,0)
            self.assertEqual(command('import-bank').returncode,0)
            self.assertNotEqual(command('import-bank').returncode,0)
            server.load_bank()
            a=self.attempt()
            self.assertEqual([q['id'] for q in a['questions']],['reviewed-test-import'])
            self.assertEqual(a['questions'][0]['reviewed_by'],'Test reviewer')
        finally:
            (server.DATA/'imported.json').unlink(missing_ok=True)
            source.unlink(missing_ok=True)
            server.load_bank()

    def test_every_subject_and_language_end_to_end(self):
        for language in ['ru','kk','en']:
            client=self.new_client()
            self.assertEqual(self.request('/api/register','POST',{'email':language+'-'+self.email,'password':'Long-password-123','language':language},client)[0],200)
            visited=set()
            for pair in server.PAIRS:
                profile={'name':'Tester','grade':'11','language':language,'profilePair':pair}
                self.assertEqual(self.request('/api/profile','PUT',{'profile':profile},client)[0],200)
                catalog=self.request('/api/catalog',client=client)[1]
                self.assertEqual(len(catalog),5)
                for subject in catalog:
                    if subject['id'] in visited:continue
                    visited.add(subject['id'])
                    status,a=self.request('/api/attempts','POST',{'subject':subject['id']},client)
                    self.assertEqual(status,201)
                    self.assertEqual(len(a['questions']),5)
                    answers=[server.BANK[q['id']]['correct_idx'] for q in a['questions']]
                    _,result=self.request('/api/attempts/'+a['id']+'/submit','POST',{'answers':answers},client)
                    self.assertEqual(result['score'],5)
                    payload={'attemptId':a['id'],'questionId':a['questions'][0]['id']}
                    status,review=self.request('/api/review','POST',payload,client)
                    self.assertEqual(status,200)
                    self.assertNotIn('correct_idx',review['practice'])
            self.assertEqual(visited,server.SUBJECTS)

    def test_existing_database_migration_preserves_records(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Path(directory)/'ubt.sqlite3'
            with sqlite3.connect(old) as db:
                db.execute('CREATE TABLE checks(id INTEGER PRIMARY KEY,user_id TEXT,question_id TEXT,correct INTEGER,created REAL)')
                db.execute("INSERT INTO checks VALUES(1,'existing','question',0,123)")
            with patch.object(server,'DATA',Path(directory)):
                server.initialize()
                with server.database() as db:
                    row=db.execute('SELECT * FROM checks').fetchone()
                    self.assertEqual(row['user_id'],'existing')
                    self.assertEqual(row['correct'],0)
                    self.assertEqual(row['independent'],1)

    def test_ai_provider_auth_quota_and_malformed_response(self):
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id'],'reasoning':'Я не понимаю этот шаг решения'}
        for code,message in [(401,'AI key or model access rejected'),(429,'AI quota or rate limit reached')]:
            error=urllib.error.HTTPError('https://api.openai.com',code,'provider error',{},None)
            with patch.dict(os.environ,{'UBT_AI_API_KEY':'test-only'}),patch.object(server.urllib.request,'urlopen',side_effect=error):
                status,result=self.request('/api/agent','POST',payload)
                self.assertIn(status,[502,503])
                self.assertIn(message,result['error'])
        class Empty:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"choices":[]}'
        with patch.dict(os.environ,{'UBT_AI_API_KEY':'test-only'}),patch.object(server.urllib.request,'urlopen',return_value=Empty()):
            self.assertEqual(self.request('/api/agent','POST',payload)[0],502)

    def test_ai_diagnostics_are_specific_and_do_not_expose_provider_body(self):
        import io
        import ssl
        a,r=self.completed();payload={'attemptId':a['id'],'questionId':r['questions'][0]['id'],'reasoning':'Помоги понять этот шаг решения'}
        cases=[
            (urllib.error.URLError(ssl.SSLCertVerificationError('certificate failed')),'ai_tls'),
            (urllib.error.URLError(TimeoutError('slow')),'ai_timeout'),
            (urllib.error.URLError('connection failed'),'ai_connection'),
            (TimeoutError('slow'),'ai_timeout'),
        ]
        for status,code in [(400,'ai_request'),(404,'ai_model'),(503,'ai_provider')]:
            cases.append((urllib.error.HTTPError('https://api.openai.com',status,'provider error',{},io.BytesIO(b'{"error":{"message":"DO_NOT_EXPOSE_PROVIDER_BODY"}}')),code))
        cases.append((urllib.error.HTTPError('https://api.openai.com',403,'provider error',{},io.BytesIO(b'{"error":{"code":"unsupported_country_region_territory","message":"DO_NOT_EXPOSE_PROVIDER_BODY"}}')),'ai_region'))
        for failure,expected in cases:
            with patch.dict(os.environ,{'UBT_AI_API_KEY':'test-only'}),patch.object(server.urllib.request,'urlopen',side_effect=failure):
                status,result=self.request('/api/agent','POST',payload)
                self.assertGreaterEqual(status,500)
                self.assertEqual(result['code'],expected)
                self.assertNotIn('DO_NOT_EXPOSE',json.dumps(result))

    def test_render_https_origin_and_explicit_override(self):
        credentials={'email':self.email,'password':'Long-password-123'}
        with patch.dict(os.environ,{'RENDER_EXTERNAL_URL':'https://ubt-test.onrender.com'},clear=True):
            self.assertEqual(self.request('/api/login','POST',credentials,headers={'Origin':'https://ubt-test.onrender.com'})[0],200)
            self.assertEqual(self.request('/api/login','POST',credentials,headers={'Origin':'https://evil.example','X-Forwarded-Proto':'https'})[0],403)
            with patch.dict(os.environ,{'UBT_ORIGIN':'https://custom.example/'}):
                self.assertEqual(self.request('/api/login','POST',credentials,headers={'Origin':'https://custom.example'})[0],200)
                self.assertEqual(self.request('/api/login','POST',credentials,headers={'Origin':'https://ubt-test.onrender.com'})[0],403)

    def test_rate_limit(self):
        with patch.dict(server.LIMITS,{},clear=True):
            server.throttle(('unit',self.email),1,60)
            with self.assertRaises(server.Problem) as e:server.throttle(('unit',self.email),1,60)
            self.assertEqual(e.exception.status,429)

if __name__=='__main__':unittest.main()
