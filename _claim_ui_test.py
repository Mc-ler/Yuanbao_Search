import asyncio, base64, json, subprocess, tempfile, shutil, urllib.request, sys
from pathlib import Path
import websockets
sys.stdout.reconfigure(encoding='utf-8')
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
PORT = 9224
BASE = 'http://127.0.0.1:8013/'

class CDP:
    def __init__(self, ws): self.ws=ws; self.n=0
    async def call(self, method, params=None):
        self.n += 1
        await self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params or {}}))
        while True:
            msg=json.loads(await self.ws.recv())
            if msg.get('id') == self.n:
                if 'error' in msg: raise RuntimeError(msg['error'])
                return msg.get('result', {})

async def main():
    profile=tempfile.mkdtemp(prefix='claim-ui-')
    proc=subprocess.Popen([CHROME,'--headless=new','--disable-gpu','--hide-scrollbars','--remote-debugging-port=9224',f'--user-data-dir={profile}','--window-size=1440,1800','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        targets=None
        for _ in range(50):
            try:
                targets=json.loads(urllib.request.urlopen('http://127.0.0.1:9224/json/list',timeout=2).read())
                if targets: break
            except Exception: pass
            await asyncio.sleep(0.2)
        target=next(t for t in targets if t.get('type')=='page')
        async with websockets.connect(target['webSocketDebuggerUrl'], max_size=None, open_timeout=5) as ws:
            cdp=CDP(ws)
            await cdp.call('Page.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', {'width':1440,'height':1800,'deviceScaleFactor':1,'mobile':False})
            await cdp.call('Page.navigate', {'url':BASE})
            await asyncio.sleep(2)
            async def ev(expr):
                r=await cdp.call('Runtime.evaluate', {'expression':expr,'returnByValue':True,'awaitPromise':True})
                return (r.get('result') or {}).get('value')
            print('title', await ev('document.title'))
            await ev('document.querySelector(\'[data-tab="verify"]\').click(); document.getElementById("verifyInput").value = "2024年全国居民人均可支配收入为41314元。"; document.getElementById("verifyRunBtn").click(); true')
            state=''
            for _ in range(60):
                await asyncio.sleep(1)
                state=await ev('document.getElementById("verifyState").textContent') or ''
                if state in ('已完成','失败'): break
            print('state', state)
            print('notice', await ev('document.getElementById("notice").textContent'))
            print('cards', await ev('document.querySelectorAll("#verifyResults .result-card").length'))
            print('result', (await ev('document.getElementById("verifyResults").innerText') or '')[:500])
            shot=await cdp.call('Page.captureScreenshot', {'format':'png','captureBeyondViewport':True})
            Path('deliverables/screenshots/v3-verify-live.png').write_bytes(base64.b64decode(shot['data']))
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

asyncio.run(main())
