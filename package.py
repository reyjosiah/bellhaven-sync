"""Package only reviewed source and instructions; never glob the private directory."""
from pathlib import Path
import zipfile,re
ROOT=Path(__file__).resolve().parent
FILES=['bellhaven.py','webapp.py','test_bellhaven.py','requirements.txt','requirements-dev.txt','README.md','WALKTHROUGH.md','WRITEUP_DRAFT.md','run_daily.sh','package.py','.gitignore']
FILES += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'templates').glob('*.html'))]
with zipfile.ZipFile(ROOT/'bellhaven-submission.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in FILES:
        data=(ROOT/name).read_bytes()
        if re.search(rb'bh_[A-Za-z0-9_-]{16,}',data):raise ValueError('Possible assessment credential in '+name)
        z.writestr('bellhaven-sync/'+name,data)
print('Created bellhaven-submission.zip with',len(FILES),'source/documentation files. No private data included.')
