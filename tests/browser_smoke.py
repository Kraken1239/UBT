"""Optional Chromium smoke test: python3 tests/browser_smoke.py (requires Playwright)."""
import json
import os
from pathlib import Path
import socket
import sys
import shutil
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ubt-browser-') as data:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    environment=dict(os.environ,UBT_DATA_DIR=data)
    environment.pop('UBT_AI_API_KEY',None);environment.pop('OPENAI_API_KEY',None)
    def start():
        process=subprocess.Popen([sys.executable,'server.py','--port',str(port)],cwd=ROOT,env=environment,stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'/api/health',timeout=.2).close()
                return process
            except OSError:time.sleep(.05)
        process.terminate();raise RuntimeError('Server did not start')
    process=start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('UBT_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
            browser.on('disconnected',lambda:None)
            context=browser.new_context(viewport={'width':1365,'height':1000})
            page=context.new_page();page.set_default_timeout(10000);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if 'Content Security Policy' in m.text else None)
            page.goto(url)
            page.get_by_role('button',name='Нет аккаунта? Создать',exact=True).click()
            page.locator('[name=email]').fill('browser-test@example.com')
            page.locator('[name=password]').fill('Browser-test-password-42')
            page.locator('#auth-form button').click()
            page.get_by_role('heading',name='Пойми ошибку. Сделай следующий шаг.').wait_for()
            page.get_by_role('button',name='Предметы',exact=True).click()
            bank=json.loads((ROOT/'content/demo.json').read_text(encoding='utf-8'))
            keys={q['id']:q for q in bank}
            practice_keys={q['recheck']['prompt']:q['recheck']['options'][q['recheck']['correct_idx']] for q in bank}
            with page.expect_response('**/api/attempts') as response:
                page.locator('[data-start=math_lit]').click()
            attempt=response.value.json()
            assert len(attempt['questions'])==5
            for i,q in enumerate(attempt['questions']):
                wrong=(keys[q['id']]['correct_idx']+1)%len(q['options'])
                page.locator(f'[name=answer][value="{wrong}"]').check()
                if i==1:
                    page.get_by_role('button',name='Назад',exact=True).click()
                    assert page.locator('[name=answer]:checked').count()==1
                    page.get_by_role('button',name='Далее',exact=True).click()
                    assert page.locator('[name=answer]:checked').count()==1
                page.get_by_role('button',name='Завершить тест' if i==4 else 'Далее',exact=True).click()
            page.get_by_role('heading',name='Результат: 0 / 5').wait_for()
            with page.expect_response('**/api/review') as response:
                page.get_by_role('button',name='Разобрать ошибку',exact=True).first.click()
            review_id=response.value.json()['question']['id']
            practice=response.value.json()['practice']
            page.locator('textarea').fill('Я умножил цену на 25 и не разделил на сто.')
            page.get_by_role('button',name='Показать подготовленный разбор',exact=True).click()
            page.get_by_text('Подготовленный ответ, без анализа AI',exact=True).first.wait_for()
            # Regression: two incorrect practice attempts, then a correct one on
            # the same review page. Never leave, sign out, or reopen the review.
            for turn in range(3):
                correct=practice['options'].index(practice_keys[practice['prompt']])
                selected=(correct+1)%len(practice['options']) if turn<2 else correct
                page.locator(f'[name=answer][value="{selected}"]').check()
                page.get_by_role('button',name='Проверить ответ',exact=True).click()
                page.locator('#check-feedback .warning' if turn<2 else '#check-feedback .success').wait_for()
                if turn<2:
                    with page.expect_response('**/api/practice/new') as response:
                        page.get_by_role('button',name='Ещё задача на этот навык',exact=True).click()
                    next_practice=response.value.json()['practice']
                    assert next_practice['id']!=practice['id']
                    assert next_practice['prompt']!=practice['prompt']
                    practice=next_practice
            page.reload()
            page.get_by_role('heading',name='Пойми ошибку. Сделай следующий шаг.').wait_for()
            page.get_by_role('button',name='История',exact=True).click()
            page.locator(f'[data-result="{attempt["id"]}"]').click()
            page.locator(f'[data-review="{review_id}"]').click()
            page.locator('#check-feedback .success').wait_for()
            page.get_by_text('Подготовленный ответ, без анализа AI',exact=True).first.wait_for()
            # An AI provider error must leave the form usable for retry.
            page.route('**/api/agent',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':'AI quota or rate limit reached; check provider billing and retry later'})))
            page.locator('textarea').fill('Почему мой способ не работает?')
            page.get_by_role('button',name='Показать подготовленный разбор',exact=True).click()
            page.locator('#notice.error').wait_for()
            assert page.get_by_role('button',name='Показать подготовленный разбор',exact=True).is_enabled()
            assert page.locator('textarea').input_value()=='Почему мой способ не работает?'
            page.unroute('**/api/agent')
            page.get_by_role('button',name='Показать подготовленный разбор',exact=True).click()
            page.locator('.chat-turn').nth(1).wait_for()
            page.get_by_role('button',name='Обзор',exact=True).click()
            page.get_by_text('Первичное понимание',exact=True).first.wait_for()
            page.reload()
            page.get_by_text('Первичное понимание',exact=True).first.wait_for()
            page.get_by_role('button',name='Профиль',exact=True).click()
            page.locator('[name=name]').fill('<img src=x onerror=alert(1)>')
            page.locator('#profile-form [name=language]').select_option('kk')
            page.get_by_role('button',name='Сохранить',exact=True).click()
            page.get_by_role('heading',name='Профиль',exact=True).wait_for()
            page.get_by_role('button',name='Пәндер',exact=True).click()
            page.locator('[data-start=math_lit]').wait_for()
            assert page.locator('[data-start]').count()==5
            page.get_by_role('button',name='Шолу',exact=True).click()
            page.get_by_role('heading',name='Қатені түсін. Келесі қадамды жаса.').wait_for()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            artifacts=Path(os.environ.get('UBT_ARTIFACTS',str(Path(tempfile.gettempdir())/'ubt-artifacts')));artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts/'ubt-mobile.png'),full_page=True)
            # Server restart must preserve account, session and progress.
            process.terminate();process.wait(timeout=5);process=start()
            page.reload()
            page.get_by_role('heading',name='Қатені түсін. Келесі қадамды жаса.').wait_for()
            page.get_by_text('Алғашқы түсіну',exact=True).first.wait_for()
            second=browser.new_context();other=second.new_page();other.set_default_timeout(10000);other.goto(url)
            other.locator('[name=email]').fill('browser-test@example.com')
            other.locator('[name=password]').fill('Browser-test-password-42')
            other.locator('#auth-form button').click()
            other.get_by_text('Алғашқы түсіну',exact=True).first.wait_for()
            other.get_by_role('button',name='Тарих',exact=True).click()
            other.get_by_role('cell',name='0 / 5',exact=True).wait_for()
            # Exercise every profile pair in all three UI languages, including
            # navigation cancellation and answer preservation on Back.
            all_pairs={'Math-Informatics':'informatics','Math-Physics':'physics','Biology-Chemistry':'chemistry','WorldHistory-Law':'law'}
            for language in ['ru','kk','en']:
                for pair,last_subject in all_pairs.items():
                    other.locator('#nav [data-page=profile]').click()
                    other.locator('#profile-form').wait_for()
                    other.locator('#profile-form [name=pair]').select_option(pair)
                    other.locator('#profile-form [name=language]').select_option(language)
                    other.locator('#profile-form button').click()
                    other.locator('#notice.success').wait_for()
                    other.locator('#nav [data-page=subjects]').click()
                    other.locator(f'[data-start={last_subject}]').wait_for()
                    assert other.locator('[data-start]').count()==5
                    other.locator(f'[data-start={last_subject}]').click()
                    other.locator('#question-form').wait_for()
                    assert other.locator('[data-action=prev]').is_disabled()
                    other.locator('[name=answer][value="1"]').check()
                    other.locator('#question-form [type=submit]').click()
                    other.locator('[data-action=prev]').click()
                    assert other.locator('[name=answer]:checked').input_value()=='1'
                    other.once('dialog',lambda d:d.dismiss())
                    other.locator('#nav [data-page=home]').click()
                    assert other.locator('#question-form').is_visible()
                    other.once('dialog',lambda d:d.accept())
                    other.locator('#nav [data-page=home]').click()
                    other.locator('.hero').wait_for()
            # Unanswered submission: cancel keeps the test, accept saves it once.
            other.locator('#nav [data-page=subjects]').click()
            other.locator('[data-start=math_lit]').click()
            for _ in range(4):other.locator('#question-form [type=submit]').click()
            other.once('dialog',lambda d:d.dismiss())
            other.locator('#question-form [type=submit]').click()
            assert other.locator('#question-form').is_visible()
            other.once('dialog',lambda d:d.accept())
            other.locator('#question-form [type=submit]').click()
            other.get_by_role('heading',name='Result: 0 / 5',exact=True).wait_for()
            # UI-only mock: configured AI response must be escaped, not executed.
            def configured(route):
                response=route.fetch();body=response.json();body['ai']=True
                route.fulfill(response=response,json=body)
            other.route('**/api/me',configured)
            other.route('**/api/agent',lambda route:route.fulfill(json={'mode':'ai','response':'Hint: <img src=x onerror=alert(1)> compare your steps.'}))
            other.reload()
            other.locator('#nav [data-page=history]').click()
            other.locator('[data-result]').first.click()
            other.locator('[data-review]').first.click()
            other.locator('textarea').fill('Please explain my specific reasoning error.')
            other.get_by_role('button',name='Discuss with AI',exact=True).click()
            other.get_by_text('AI feedback on your reasoning',exact=True).wait_for()
            assert other.locator('#agent-response img').count()==0
            assert '<img src=x' in other.locator('#agent-response').inner_text()
            other.unroute('**/api/me');other.unroute('**/api/agent')
            other.locator('[data-action=logout]').click()
            other.locator('[name=email]').fill('browser-test@example.com')
            other.locator('[name=password]').fill('wrong-password-here')
            other.locator('#auth-form button').click()
            other.locator('#notice.error').wait_for()
            assert other.locator('#auth-form button').is_enabled()
            assert not errors,errors
            browser.close()
            print(json.dumps({'passed':['registration','diagnostic','server grading','prepared agent fallback','wrong twice then correct on same review page','practice and conversation survive reload','AI error retry preserves input','progress','reload','Kazakh UI','mobile layout','server restart persistence','second browser login and sync','12 UI language/profile combinations','navigation cancel and confirm','Back preserves answer','unanswered submit cancel and confirm','AI UI mock renders text safely','logout and wrong password','no JS or CSP errors']},ensure_ascii=False))
    finally:
        process.terminate();process.wait(timeout=5)
