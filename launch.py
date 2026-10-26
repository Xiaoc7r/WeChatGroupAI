import os
import sys
import runpy
import traceback
import ctypes
from pathlib import Path

base=Path(__file__).resolve().parent
os.chdir(base)
sys.path.insert(0,str(base))
# Third-party diagnostics may expose local identifiers; keep them off disk.
sys.stdout=open(os.devnull,'w',encoding='utf-8')
sys.stderr=sys.stdout
try:
    runpy.run_path(str(base/'app.py'),run_name='__main__')
except Exception:
    (base/'startup-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
    ctypes.windll.user32.MessageBoxW(None,'启动失败，详情位于程序目录 startup-error.txt。','微信群 AI',16)
