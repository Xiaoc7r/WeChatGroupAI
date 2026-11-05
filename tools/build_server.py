"""Rebuild the one server ZIP using an explicit file allowlist; never include data/."""
from pathlib import Path
import hashlib
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('app.py','core.py','features.py','engine.py','launch.py','requirements.txt','requirements-lock.txt',
       'README.md','使用指南.md','UPDATE.cmd','Update.ps1','Install.cmd','install-server.ps1','Start.cmd',
       'Disconnect-Keep-WeChat.cmd','Repair-WeChatGroupAI.cmd','Server-Resource-Check.cmd')

def build():
    destination=ROOT/'server'
    destination.mkdir(exist_ok=True)
    package=destination/'WeChatGroupAI-server.zip'
    privacy=(r'wxid_[A-Za-z0-9_]+',r'sk-[A-Za-z0-9_-]{16,}',
             r'gh[pousr]_[A-Za-z0-9]{16,}',r'github_pat_[A-Za-z0-9_]+',
             r'-----BEGIN .*PRIVATE KEY-----')
    hashes=[]
    for name in FILES:
        data=(ROOT/name).read_bytes()
        source=data.decode('utf-8-sig')
        if any(re.search(pattern,source) for pattern in privacy):raise RuntimeError('Privacy check: '+name)
        if name.endswith('.py'):compile(source,name,'exec')
        hashes.append(hashlib.sha256(data).hexdigest()+'  '+name)
    temporary=package.with_suffix('.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
        for name in FILES:z.write(ROOT/name,name)
        z.writestr('SHA256SUMS.txt','\n'.join(hashes)+'\n')
    with zipfile.ZipFile(temporary) as z:
        assert z.testzip() is None
        assert set(z.namelist())==set(FILES)|{'SHA256SUMS.txt'}
    temporary.replace(package)
    (destination/'SHA256.txt').write_text(hashlib.sha256(package.read_bytes()).hexdigest()+'  '+package.name+'\n',encoding='ascii')
    print('Built and verified:',package)

if __name__=='__main__':build()
