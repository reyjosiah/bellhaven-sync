"""Read-only discovery and explicit, durable, reviewer-approved CRM corrections."""
from __future__ import annotations
import argparse, contextlib, difflib, fcntl, hashlib, json, os, re, sqlite3, time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BASE = 'https://analyst-assessment-production.up.railway.app'
FIELDS = ('name','parent_id','billing_street','billing_city','billing_state','billing_zip','care_type','status','phone','lifetime_revenue','outstanding_ar','chow_current_account','duplicate_of_account','note')
CARE = {'memory support':'Memory Care','short-term rehabilitation & nursing':'Skilled Nursing','assisted living':'Assisted Living'}

def now(): return datetime.now(timezone.utc).isoformat()
def packed(x): return json.dumps(x,sort_keys=True,ensure_ascii=False)
def fingerprint(x): return hashlib.sha256(packed(x).encode()).hexdigest()
def norm(x): return ' '.join(re.findall(r'[a-z0-9]+',str(x or '').lower().replace('&',' and ')))
def street(x):
    aliases={'street':'st','road':'rd','avenue':'ave','boulevard':'blvd','lane':'ln','drive':'dr','court':'ct','place':'pl','parkway':'pkwy','north':'n','south':'s','east':'e','west':'w','northwest':'nw','northeast':'ne','southwest':'sw','southeast':'se'}
    return ' '.join(aliases.get(t,t) for t in norm(x).split())
def pobox(x): return bool(re.search(r'\bp\s*o\s*box\b|\bpo box\b',norm(x)))
def care(x):
    parts = x if isinstance(x,list) else re.split(r'\s*[;,|]\s*',x or '')
    return '; '.join(sorted(set(CARE.get(str(p).lower(),str(p).strip()) for p in parts if str(p).strip())))
def money(x):
    if x is None or isinstance(x,bool) or str(x).strip()=='': raise ValueError('Missing financial value')
    try: value=Decimal(str(x))
    except InvalidOperation: raise ValueError('Invalid financial value')
    if not value.is_finite() or value<0: raise ValueError('Invalid financial value')
    return value

def protected(a):
    revenue=money(a.get('lifetime_revenue')); ar=money(a.get('outstanding_ar'))
    return revenue>0 and ar>0
def snapshot(a): return {k:a.get(k) for k in FIELDS}
def append_note(old,text): return old if text in (old or '') else '\n'.join(filter(None,[old,text]))

class API:
    def __init__(self,token=None):
        self.token=token or os.environ.get('BELLHAVEN_TOKEN')
        if not self.token: raise ValueError('Set BELLHAVEN_TOKEN in your private .env file.')
        self.session=requests.Session()
    def request(self,method,path,payload=None):
        # Never include the token in a URL, exception, or public request session.
        r=self.session.request(method,BASE+'/api/v1'+path,json=payload,headers={'Authorization':'Bearer '+self.token},timeout=25,allow_redirects=False)
        if not 200<=r.status_code<300: raise RuntimeError(f'CRM {method} failed: HTTP {r.status_code}; no automatic write retry.')
        return r.json()
    def all(self):
        rows=[]; page=1; total=None
        while True:
            d=self.request('GET',f'/accounts?page={page}&page_size=50')
            if not isinstance(d,dict) or not isinstance(d.get('data'),list): raise ValueError('Unexpected CRM response')
            if total is not None and d['total']!=total: raise ValueError('CRM changed during pagination; rerun')
            total=d['total']; rows.extend(d['data'])
            if len(rows)>=total: break
            if not d['data']: raise ValueError('Incomplete CRM pagination')
            page+=1
        if len(rows)!=total or len({a['account_id'] for a in rows})!=total: raise ValueError('Incomplete or overlapping CRM pages')
        return rows
    def get(self,aid):
        d=self.request('GET','/accounts/'+aid)
        return d.get('data',d)
    def create(self,data):
        d=self.request('POST','/accounts',data)
        return d.get('data',d)
    def patch(self,aid,data):
        d=self.request('PATCH','/accounts/'+aid,data)
        return d.get('data',d)

def parse_location(html,url):
    s=BeautifulSoup(html,'html.parser'); title=s.select_one('h1')
    values={dt.get_text(' ',strip=True).lower():dt.find_next_sibling('dd') for dt in s.select('dt')}
    addr=values.get('address'); offerings=values.get('care offerings')
    if title is None or addr is None or offerings is None: raise ValueError('Missing location fields: '+url)
    lines=list(addr.stripped_strings)
    text=addr.get_text(' ',strip=True)
    m=re.search(r'(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$',lines[-1])
    if len(lines)<2 or not m: raise ValueError('Unrecognized address: '+url)
    badges=offerings.select('.badge')
    offerings_text=[b.get_text(' ',strip=True) for b in badges] or list(offerings.stripped_strings)
    return {'url':url,'name':title.get_text(' ',strip=True),'billing_street':' '.join(lines[:-1]),'billing_city':m[1].strip(),'billing_state':m[2],'billing_zip':m[3], 'care_type':care(offerings_text),'offerings':offerings_text,'source_text':s.select_one('.wrap').get_text('\n',strip=True),'retrieved_at':now()}

def crawl(fetch=None):
    def default_fetch(url):
        r=requests.get(url,timeout=25,allow_redirects=False); r.raise_for_status()
        if r.status_code!=200: raise ValueError('Unexpected page response')
        return r.text
    fetch=fetch or default_fetch
    queue=[BASE+'/',BASE+'/about',BASE+'/communities']; seen=set(); locations={}; pages=[]; errors=[]; counts=[]
    while queue:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url)
        if len(seen)>150: errors.append('Crawl exceeded page safety limit');break
        try:
            html=fetch(url); s=BeautifulSoup(html,'html.parser'); text=s.get_text(' ',strip=True)
            pages.append({'url':url,'retrieved_at':now(),'source_text':text})
            counts += [int(x) for x in re.findall(r'(\d+) communities (?:listed|and growing)',text)]
            if urlparse(url).path.startswith('/communities/'):
                locations[url]=parse_location(html,url)
            for a in s.select('a[href]'):
                link=urljoin(url,a['href']).split('#')[0]; u=urlparse(link)
                if u.scheme=='https' and u.netloc==urlparse(BASE).netloc and (u.path in ('/','/about','/communities') or u.path.startswith('/communities/')) and link not in seen:
                    if link not in queue: queue.append(link)
        except Exception as e: errors.append(f'{url}: {type(e).__name__}: {e}')
    # Count mismatch is a safety failure, never evidence of a sale.
    expected=max(counts) if counts else None
    if expected is None or len(locations)<expected: errors.append(f'Completeness check: {len(locations)} locations, expected at least {expected}')
    return {'locations':list(locations.values()),'pages':pages,'complete':not errors,'errors':errors,'expected':expected}

def same_place(l,a):
    return bool(l['billing_street'] and a.get('billing_street') and not pobox(a['billing_street']) and street(l['billing_street'])==street(a['billing_street']) and norm(l['billing_city'])==norm(a.get('billing_city')) and norm(l['billing_state'])==norm(a.get('billing_state')))
def plausible(l,a):
    if norm(l['billing_state'])!=norm(a.get('billing_state')): return False
    if same_place(l,a):return True
    city=norm(l['billing_city'])==norm(a.get('billing_city'))
    similarity=difflib.SequenceMatcher(None,norm(l['name']),norm(a['name'])).ratio()
    return (city and similarity>=.45) or similarity>=.92

def make_proposal(kind,l,accounts,changes,reason,blocked=False):
    return {'kind':kind,'facility':l,'accounts':accounts,'changes':changes,'reason':reason,'blocked':blocked}

def change_proposal(l,a,parent):
    desired={k:l[k] for k in ('name','billing_street','billing_city','billing_state','billing_zip','care_type')}
    desired['parent_id']=parent; desired['status']='Active'
    changes={}
    for k,v in desired.items():
        old=a.get(k,'')
        equivalent=(street(old)==street(v) if k=='billing_street' else care(old)==care(v) if k=='care_type' else str(old)[:5]==str(v)[:5] if k=='billing_zip' else norm(old)==norm(v))
        if not equivalent: changes[k]=v
    if not changes: return None
    if a.get('parent_id')!=parent:
        try: needs_new=protected(a)
        except ValueError:
            return make_proposal('blocked',l,[a],changes,'Ownership change blocked: financial fields are missing or invalid.',True)
        if needs_new:
            new={**desired,'lifetime_revenue':0,'outstanding_ar':0,'note':'Bellhaven reconciliation: replacement for '+a['account_id']+'; source '+l['url']}
            return make_proposal('ownership',l,[a],{'create':new,'old_account_link':'<new account ID>'},'Billing safeguard: create a replacement; preserve the old account except its CHOW link.')
    changes['note']=append_note(a.get('note',''),'Bellhaven reconciliation: verified published details and ownership at '+l['url'])
    return make_proposal('update',l,[a],changes,'Unique match by normalized address or name and locality; update only the displayed differences.')

def generate(crawl_result,accounts,selections=None):
    selections=selections or {}
    parents=[a for a in accounts if norm(a['name'])=='bellhaven senior living parent account']
    if len(parents)!=1: raise ValueError('Expected exactly one Bellhaven corporate parent')
    parent=parents[0]['account_id']
    facilities=[a for a in accounts if not a['name'].endswith('(Parent Account)')]
    live=[a for a in facilities if not a.get('duplicate_of_account') and not a.get('chow_current_account')]
    proposals=[]; matches=[]; covered=set()
    for l in crawl_result['locations']:
        duplicate_found=False
        candidates=[a for a in live if plausible(l,a)]
        exact=[a for a in candidates if same_place(l,a)]
        byname=[a for a in candidates if norm(a['name'])==norm(l['name']) and norm(a.get('billing_city'))==norm(l['billing_city']) and (not a.get('billing_street'))]
        strong=exact or byname
        selected=selections.get(l['url'])
        if selected:
            chosen=next((a for a in candidates if a['account_id']==selected['account_id']),None)
            if chosen is not None: strong=[chosen]
        covered.update(a['account_id'] for a in candidates)
        if len(strong)>1 and all(same_place(l,a) for a in strong):
            try:
                balances=[(a,money(a.get('lifetime_revenue')),money(a.get('outstanding_ar'))) for a in strong]
                financial=[a for a,rev,ar in balances if rev>0 or ar>0]
                if len(financial)>1: raise ValueError('Several copies have financial history')
                ordered=sorted(strong,key=lambda a:(-(a in financial),-(a.get('parent_id')==parent),-sum(bool(a.get(k)) for k in FIELDS),a['account_id']))
                chosen=ordered[0]
                for loser in ordered[1:]:
                    changes={'duplicate_of_account':chosen['account_id'],'status':'Inactive','note':append_note(loser.get('note',''),'Bellhaven reconciliation: duplicate of '+chosen['account_id']+'; source '+l['url'])}
                    proposals.append(make_proposal('duplicate',l,[loser,chosen],changes,'Same normalized physical location; retain financial history, then correct parent, completeness, and stable ID.'))
                duplicate_found=True
                strong=[chosen]
            except ValueError as e:
                strong=[]
                proposals.append(make_proposal('ambiguous',l,candidates,{},str(e)+'; reviewer must resolve.',True))
                matches.append({'facility':l,'classification':'Needs review'});continue
        if len(strong)==1:
            p=change_proposal(l,strong[0],parent)
            if p:
                if selected: p['reason']='Reviewer-selected match: '+selected['reason']+' '+p['reason']
                proposals.append(p)
            matches.append({'facility':l,'classification':'Needs fix' if p or duplicate_found else 'Already correct','account_id':strong[0]['account_id']})
        elif candidates:
            proposals.append(make_proposal('ambiguous',l,candidates,{},'Names or addresses conflict, or several accounts are plausible. Select a candidate only after reviewing the evidence.',True))
            matches.append({'facility':l,'classification':'Needs review'})
        else:
            new={k:l[k] for k in ('name','billing_street','billing_city','billing_state','billing_zip','care_type')}
            new.update(parent_id=parent,status='Active',lifetime_revenue=0,outstanding_ar=0,note='Bellhaven reconciliation: new facility; source '+l['url'])
            proposals.append(make_proposal('create',l,[],new,'No plausible existing account in the complete CRM.'))
            matches.append({'facility':l,'classification':'Missing'})
    if crawl_result['complete']:
        for a in live:
            if a.get('parent_id')==parent and a['account_id'] not in covered:
                note=append_note(a.get('note',''),'Bellhaven reconciliation: absent from a complete website crawl. Ownership or closure unconfirmed; investigate before re-parenting.')
                if a.get('status')!='Needs Review' or note!=a.get('note',''):
                    proposals.append(make_proposal('absent',{'name':a['name'],'url':BASE+'/communities','source_text':'Not found among '+str(len(crawl_result['locations']))+' locations in a complete crawl. This is not proof of closure or sale. Pages checked: '+', '.join(x['url'] for x in crawl_result['pages'])},[a],{'status':'Needs Review','note':note},'Absent from complete website results; flag for investigation without inventing a new owner.'))
    return proposals,matches,parent

class Store:
    def __init__(self,path=None):
        self.path=Path(path or ROOT/'private'/'review.sqlite3');self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,at TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,run_id INTEGER,payload TEXT,status TEXT,progress TEXT DEFAULT '{}',error TEXT DEFAULT '',decision_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT,proposal_id TEXT,event TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS selections(url TEXT PRIMARY KEY,account_id TEXT,reason TEXT);''')
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row
        try:yield c;c.commit()
        except: c.rollback();raise
        finally:c.close()
    @contextlib.contextmanager
    def lock(self):
        with open(str(self.path)+'.lock','a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def event(self,pid,event,payload):
        with self.db() as c:c.execute('INSERT INTO audit(at,proposal_id,event,payload) VALUES(?,?,?,?)',(now(),pid,event,packed(payload)))
    def save_run(self,result,accounts):
        with self.db() as c:selections={r['url']:dict(r) for r in c.execute('SELECT * FROM selections')}
        proposals,matches,parent=generate(result,accounts,selections)
        payload={**result,'accounts':accounts,'matches':matches,'parent_id':parent}
        with self.db() as c:
            rid=c.execute('INSERT INTO runs(at,payload) VALUES(?,?)',(now(),packed(payload))).lastrowid
            c.execute("UPDATE proposals SET status='superseded' WHERE status='pending'")
            for p in proposals:
                key={k:p[k] for k in ('kind','changes')};key['facility']=p['facility']['url'];key['accounts']=[snapshot(a) for a in p['accounts']];key['ids']=[a['account_id'] for a in p['accounts']]
                pid=fingerprint(key)
                c.execute("INSERT INTO proposals(id,run_id,payload,status) VALUES(?,?,?,'pending') ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,status=CASE WHEN proposals.status='superseded' THEN 'pending' ELSE proposals.status END",(pid,rid,packed(p)))
        return rid,len(proposals)
    def row(self,pid):
        with self.db() as c:r=c.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
        if r is None:raise ValueError('Unknown proposal')
        return dict(r)
    def update(self,pid,**kw):
        allowed={'status','progress','error','decision_at'}
        if not set(kw)<=allowed:raise ValueError('Invalid state field')
        with self.db() as c:c.execute('UPDATE proposals SET '+','.join(k+'=?' for k in kw)+' WHERE id=?',(*[packed(v) if isinstance(v,dict) else v for v in kw.values()],pid))

class Reviewer:
    def __init__(self,store,api):self.store=store;self.api=api
    def reject(self,pid):
        with self.store.lock():
            row=self.store.row(pid)
            if row['status']!='pending' or json.loads(row['progress']):raise ValueError('Only untouched pending proposals can be rejected')
            self.store.update(pid,status='rejected',decision_at=now());self.store.event(pid,'rejected',{})
    def approve(self,pid,confirmed=False):
        with self.store.lock():
            row=self.store.row(pid);p=json.loads(row['payload']);progress=json.loads(row['progress'])
            if row['status'] not in ('pending','error'):raise ValueError('Proposal is not approvable')
            if p['blocked']:raise ValueError('Resolve the ambiguous match before approval')
            if p['kind']=='ownership' and not confirmed:raise ValueError('Confirm the multi-step billing safeguard')
            try:
                self._apply(pid,p,progress)
                self.store.update(pid,status='approved',decision_at=now(),error='');self.store.event(pid,'approved',progress)
            except Exception as e:
                # Deliberately retain progress so a retry can reconcile uncertain writes.
                self.store.update(pid,status='error',error=str(e));self.store.event(pid,'error',{'message':str(e)})
                raise
    def _apply(self,pid,p,progress):
        old=p['accounts'][0] if p['accounts'] else None
        if not progress:
            if p['kind'] in ('create','ownership'):
                desired=p['changes']['create'] if p['kind']=='ownership' else p['changes']
                competing=[a for a in self.api.all() if not a['name'].endswith('(Parent Account)') and a['account_id'] not in [x['account_id'] for x in p['accounts']] and not a.get('duplicate_of_account') and not a.get('chow_current_account') and plausible(p['facility'],a)]
                if competing:raise ValueError('New potential match appeared since scanning; rescan before creating an account.')
            for a in p['accounts']:
                if snapshot(self.api.get(a['account_id']))!=snapshot(a):raise ValueError('Stale proposal: CRM changed. Rescan before approving.')
        elif old:
            current=self.api.get(old['account_id']); expected=snapshot(old)
            if p['kind']=='ownership':
                expected['chow_current_account']=current.get('chow_current_account')
                if current.get('chow_current_account') not in ('',None,progress.get('new_id')):raise ValueError('Conflicting CHOW link')
            elif progress.get('patch_intent'):
                # A timed-out PATCH may have applied. Verify target fields before retry.
                pass
            if p['kind']=='ownership' and snapshot(current)!=expected:raise ValueError('Old billing account changed; manual reconciliation required')
        def save(): self.store.update(pid,progress=progress)
        if p['kind'] in ('create','ownership'):
            desired=p['changes']['create'] if p['kind']=='ownership' else p['changes']
            marker=' [proposal:'+pid+']';desired={**desired,'note':desired.get('note','')+marker}
            if not progress.get('new_id'):
                if progress.get('create_intent'):
                    found=[a for a in self.api.all() if marker in (a.get('note') or '')]
                    if len(found)!=1:raise ValueError('Create outcome uncertain. Do not retry creation: reconcile manually (expected exactly one proposal marker).')
                    progress['new_id']=found[0]['account_id'];save()
                else:
                    progress['create_intent']=True;save();self.store.event(pid,'create_requested',desired)
                    created=self.api.create(desired)
                    if not created.get('account_id'):raise ValueError('Create returned no account ID; reconcile before retry')
                    progress['new_id']=created['account_id'];save()
            created=self.api.get(progress['new_id']);self._verify(created,desired)
            self.store.event(pid,'create_verified',created)
            if p['kind']=='ownership':
                if not protected(old):raise ValueError('Billing safeguard precondition changed')
                current=self.api.get(old['account_id'])
                expected=snapshot(old);expected['chow_current_account']=current.get('chow_current_account')
                if snapshot(current)!=expected or current.get('chow_current_account') not in ('',None,progress['new_id']):raise ValueError('Old account changed before linking')
                progress['link_intent']=True;save()
                if current.get('chow_current_account')!=progress['new_id']: self.api.patch(old['account_id'],{'chow_current_account':progress['new_id']})
                after=self.api.get(old['account_id']);expected=snapshot(old);expected['chow_current_account']=progress['new_id']
                if snapshot(after)!=expected:raise ValueError('Old account verification failed')
                self.store.event(pid,'old_account_preserved_and_linked',after)
        else:
            target=old['account_id'];current=self.api.get(target)
            if progress.get('patch_intent'):
                expected=snapshot(old)
                for k,v in p['changes'].items():expected[k]=v
                if snapshot(current)==expected:
                    self.store.event(pid,'patch_verified_after_retry',current);return
                if snapshot(current)!=snapshot(old):raise ValueError('Partial or conflicting PATCH; rescan and reconcile manually')
            elif snapshot(current)!=snapshot(old):raise ValueError('Stale proposal: rescan')
            # Financial check is independent of proposal generation.
            if 'parent_id' in p['changes'] and protected(current):raise ValueError('Direct re-parent blocked by billing SOP')
            progress['patch_intent']=True;save();self.store.event(pid,'patch_requested',p['changes'])
            self.api.patch(target,p['changes']);after=self.api.get(target)
            expected=snapshot(old);expected.update(p['changes'])
            if snapshot(after)!=expected:raise ValueError('PATCH verification failed or undisplayed fields changed')
            self.store.event(pid,'patch_verified',after)
    @staticmethod
    def _verify(actual,desired):
        for k,v in desired.items():
            if actual.get(k)!=v:raise ValueError('Created account verification failed for '+k)

def load_env():
    p=ROOT/'private'/'.env'
    if p.exists():
        for line in p.read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1);os.environ.setdefault(k,v)

def scan(store=None,api=None,fetch=None):
    store=store or Store();api=api or API()
    with store.lock():
        result=crawl(fetch);accounts=api.all();rid,n=store.save_run(result,accounts)
    return {'run':rid,'locations':len(result['locations']),'accounts':len(accounts),'proposals':n,'complete':result['complete'],'errors':result['errors']}

if __name__=='__main__':
    load_env();parser=argparse.ArgumentParser();parser.add_argument('command',choices=['scan','serve']);args=parser.parse_args()
    if args.command=='scan':print(json.dumps(scan(),indent=2))
    else:
        from webapp import create_app
        create_app().run(host='127.0.0.1',port=8765,debug=False)
