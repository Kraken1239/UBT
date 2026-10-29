import concurrent.futures
import http.cookiejar
import json
import os
from pathlib import Path
import sqlite3
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

    def test_recheck_first_attempt_and_delayed_status(self):
        a,r=self.completed();q=r['questions'][0]; payload={'attemptId':a['id'],'questionId':q['id']}
        data=self.request('/api/review','POST',payload)[1]
        self.assertNotIn('correct_idx',data['recheck'])
        correct=server.BANK[q['id']]['recheck']['correct_idx']
        self.assertTrue(self.request('/api/recheck','POST',dict(payload,answer=correct))[1]['correct'])
        self.assertEqual(self.request('/api/recheck','POST',dict(payload,answer=correct))[0],409)
        skills=self.request('/api/progress')[1]['skills']
        self.assertEqual(skills[0]['status'],'initial_understanding')
        with server.database() as db:db.execute('UPDATE checks SET created=created-86401 WHERE question_id=?',(q['id'],))
        self.assertEqual(self.request('/api/recheck','POST',dict(payload,answer=correct))[0],200)

    def test_wrong_check_does_not_mark_understanding(self):
        a,r=self.completed();q=r['questions'][0]
        answer=(server.BANK[q['id']]['recheck']['correct_idx']+1)%len(q['options'])
        _,r=self.request('/api/recheck','POST',{'attemptId':a['id'],'questionId':q['id'],'answer':answer})
        self.assertFalse(r['correct'])
        self.assertEqual(self.request('/api/progress')[1]['skills'][0]['status'],'needs_practice')

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
        source=server.DATA/'fixture.json';source.write_text(json.dumps([q]))
        environment=dict(os.environ,UBT_DATA_DIR=str(server.DATA))
        def command(name):
            return subprocess.run(['python3',str(server.ROOT/'server.py'),name,str(source)],env=environment,capture_output=True,text=True)
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

    def test_rate_limit(self):
        with patch.dict(server.LIMITS,{},clear=True):
            server.throttle(('unit',self.email),1,60)
            with self.assertRaises(server.Problem) as e:server.throttle(('unit',self.email),1,60)
            self.assertEqual(e.exception.status,429)

if __name__=='__main__':unittest.main()
