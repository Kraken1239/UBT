"""Optional Chromium smoke test: python3 tests/browser_smoke.py (requires Playwright)."""
import json
import os
from pathlib import Path
import socket
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
        process=subprocess.Popen(['python3','server.py','--port',str(port)],cwd=ROOT,env=environment,stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'/api/health',timeout=.2).close()
                return process
            except OSError:time.sleep(.05)
        process.terminate();raise RuntimeError('Server did not start')
    process=start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1365,'height':1000})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda m:errors.append(m.text) if 'Content Security Policy' in m.text else None)
            page.goto(url)
            page.get_by_role('button',name='Нет аккаунта? Создать',exact=True).click()
            page.locator('[name=email]').fill('browser-test@example.com')
            page.locator('[name=password]').fill('Browser-test-password-42')
            page.locator('#auth-form button').click()
            page.get_by_role('heading',name='Пойми ошибку. Сделай следующий шаг.').wait_for()
            page.get_by_role('button',name='Предметы',exact=True).click()
            page.locator('[data-start=math_lit]').click()
            page.locator('[name=answer][value="1"]').check()
            page.get_by_role('button',name='Завершить тест',exact=True).click()
            page.get_by_role('heading',name='Результат: 0 / 1').wait_for()
            page.get_by_role('button',name='Разобрать ошибку',exact=True).click()
            page.locator('textarea').fill('Я умножил цену на 25 и не разделил на сто.')
            page.get_by_role('button',name='Обсудить с AI',exact=True).click()
            page.get_by_role('heading',name='Подготовленный ответ, без анализа AI').wait_for()
            page.locator('[name=answer][value="0"]').check()
            page.get_by_role('button',name='Проверить ответ',exact=True).click()
            page.locator('#check-feedback .success').wait_for()
            page.get_by_role('button',name='Обзор',exact=True).click()
            page.get_by_text('Первичное понимание',exact=True).wait_for()
            page.reload()
            page.get_by_text('Первичное понимание',exact=True).wait_for()
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
            artifacts=Path('/workspace/artifacts');artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts/'ubt-mobile.png'),full_page=True)
            # Server restart must preserve account, session and progress.
            process.terminate();process.wait(timeout=5);process=start()
            page.reload()
            page.get_by_role('heading',name='Қатені түсін. Келесі қадамды жаса.').wait_for()
            page.get_by_text('Алғашқы түсіну',exact=True).wait_for()
            second=browser.new_context();other=second.new_page();other.goto(url)
            other.locator('[name=email]').fill('browser-test@example.com')
            other.locator('[name=password]').fill('Browser-test-password-42')
            other.locator('#auth-form button').click()
            other.get_by_text('Алғашқы түсіну',exact=True).wait_for()
            other.get_by_role('button',name='Тарих',exact=True).click()
            other.get_by_role('cell',name='0 / 1',exact=True).wait_for()
            assert not errors,errors
            browser.close()
            print(json.dumps({'passed':['registration','diagnostic','server grading','prepared agent fallback','independent recheck','progress','reload','Kazakh UI','mobile layout','server restart persistence','second browser login and sync','no JS or CSP errors']},ensure_ascii=False))
    finally:
        process.terminate();process.wait(timeout=5)
