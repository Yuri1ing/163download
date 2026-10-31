import json, os, subprocess, tempfile, threading, time, urllib.request, sys
sys.path.insert(0, os.getcwd())
from ncm.server import make_server
from ncm.shell import find_edge
from tools.drive_shot import CDP, wait

httpd, backend, port = make_server("t9")
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{port}/?t=t9"
prof = os.path.join(tempfile.gettempdir(), "ncm-anim2")
p = subprocess.Popen([find_edge(), f"--app={url}", "--window-size=1280,880",
                      f"--user-data-dir={prof}", "--no-first-run",
                      "--remote-debugging-port=9352", "--remote-allow-origins=*"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
tgt = {}


def find():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:9352/json", timeout=2).read().decode())
        for t in d:
            if t.get("type") == "page" and f":{port}" in t.get("url", ""):
                tgt["ws"] = t["webSocketDebuggerUrl"]
                return True
    except Exception:
        pass
    return False


wait(find, 40, "cdp")
c = CDP(tgt["ws"])
c.send("Page.enable")
c.send("Runtime.enable")
wait(lambda: c.js("!!document.getElementById('btnMin')"), 20, "page")
print("reduce-motion:", c.js("matchMedia('(prefers-reduced-motion: reduce)').matches"))
print("进窗动画:", c.js("getComputedStyle(document.body).animationName"))
c.js("document.getElementById('btnMin').click()")
time.sleep(0.06)
print("60ms class:", c.js("document.body.className"))
print("60ms opacity:", c.js("getComputedStyle(document.body).opacity"))
print("60ms transform:", c.js("getComputedStyle(document.body).transform"))
print("60ms 动画:", c.js("getComputedStyle(document.body).animationName"),
      c.js("getComputedStyle(document.body).animationDuration"))
print("过渡时长:", c.js("getComputedStyle(document.body).transitionDuration"))
c.close()
p.terminate()
httpd.shutdown()
