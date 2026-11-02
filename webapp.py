"""Local-only, server-rendered review UI. POST is the only route to CRM writes."""
import hmac, json, os, secrets
from urllib.parse import urlparse
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from bellhaven import API, ROOT, Store, Reviewer, change_proposal, fingerprint, now, packed, scan, snapshot

def create_app(store=None,api=None):
    store=store or Store();api=api or API();reviewer=Reviewer(store,api)
    app=Flask(__name__)
    secret=store.path.parent/'session.key'
    if not secret.exists():
        fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
    app.secret_key=secret.read_text()
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',MAX_CONTENT_LENGTH=16384)
    app.jinja_env.filters['pretty']=lambda x: json.dumps(x,indent=2,ensure_ascii=False)
    @app.before_request
    def security():
        if request.host not in ('127.0.0.1:8765','localhost:8765','localhost'):abort(400)
        session.setdefault('csrf',secrets.token_hex(32))
        if request.method=='POST':
            if not hmac.compare_digest(request.form.get('csrf',''),session['csrf']):abort(403)
            origin=request.headers.get('Origin')
            if origin and urlparse(origin).netloc!=request.host:abort(403)
    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='no-store'
        return response
    def latest():
        with store.db() as c:r=c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        return dict(r) if r else None
    @app.get('/')
    def index():
        run=latest();status=request.args.get('status','pending');kind=request.args.get('kind','')
        with store.db() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM proposals ORDER BY run_id DESC,id')]
            counts={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM proposals GROUP BY status')}
        for r in rows:r['p']=json.loads(r['payload'])
        visible=[r for r in rows if (not status or r['status']==status) and (not kind or r['p']['kind']==kind)]
        return render_template('index.html',run=run,data=json.loads(run['payload']) if run else None,rows=visible,counts=counts,status=status,kind=kind)
    @app.post('/scan')
    def rescan():
        try:result=scan(store,api);flash(f"Read-only scan finished: {result['locations']} locations; {result['proposals']} generated proposals. Previously decided items remain decided.")
        except Exception as e:flash('Scan failed: '+str(e))
        return redirect(url_for('index'))
    @app.get('/proposal/<pid>')
    def detail(pid):
        try:r=store.row(pid)
        except ValueError:abort(404)
        p=json.loads(r['payload'])
        p['write_preview']=json.loads(json.dumps(p['changes']))
        if p['kind'] in ('create','ownership'):
            destination=p['write_preview']['create'] if p['kind']=='ownership' else p['write_preview']
            destination['note']=destination.get('note','')+' [proposal:'+pid+']'
        with store.db() as c:events=[dict(e) for e in c.execute('SELECT * FROM audit WHERE proposal_id=? ORDER BY id',(pid,))]
        return render_template('detail.html',row=r,p=p,events=events,fields=('name','parent_name','parent_id','billing_street','billing_city','billing_state','billing_zip','care_type','status','lifetime_revenue','outstanding_ar','chow_current_account','duplicate_of_account','note'))
    @app.post('/proposal/<pid>/<action>')
    def decide(pid,action):
        try:
            if action=='approve':reviewer.approve(pid,request.form.get('confirmed')=='yes');flash('Approved and verified against the CRM.')
            elif action=='reject':reviewer.reject(pid);flash('Rejected. This unchanged proposal will not return on a daily scan.')
            elif action=='resolve':
                with store.lock():
                    r=store.row(pid);p=json.loads(r['payload']);aid=request.form.get('account_id')
                    if r['status']!='pending' or p['kind']!='ambiguous':raise ValueError('Not an unresolved matching proposal')
                    if not request.form.get('reason','').strip():raise ValueError('Explain the evidence for this selection')
                    a=next((a for a in p['accounts'] if a['account_id']==aid),None)
                    if a is None:raise ValueError('Choose a displayed candidate')
                    if snapshot(api.get(aid))!=snapshot(a):raise ValueError('Candidate changed; rescan first')
                    run=latest();parent=json.loads(run['payload'])['parent_id']
                    with store.db() as c:c.execute('INSERT OR REPLACE INTO selections(url,account_id,reason) VALUES(?,?,?)',(p['facility']['url'],aid,request.form['reason'].strip()))
                    new=change_proposal(p['facility'],a,parent)
                    if new:
                        new['reason']='Reviewer selected candidate: '+request.form['reason'].strip()+' '+new['reason']
                        key={'kind':new['kind'],'changes':new['changes'],'facility':new['facility']['url'],'accounts':[snapshot(x) for x in new['accounts']],'ids':[x['account_id'] for x in new['accounts']]}
                        nid=fingerprint(key)
                        with store.db() as c:
                            c.execute("INSERT OR IGNORE INTO proposals(id,run_id,payload,status) VALUES(?,?,?,'pending')",(nid,r['run_id'],packed(new)))
                        store.update(pid,status='resolved',decision_at=now());store.event(pid,'candidate_selected',{'account_id':aid,'reason':request.form['reason'],'next':nid})
                        flash('Match selected; inspect the resulting correction before approving.');return redirect(url_for('detail',pid=nid))
                    store.update(pid,status='resolved',decision_at=now());store.event(pid,'match_confirmed_no_change',{'account_id':aid,'reason':request.form['reason']});flash('Selected account already agrees with the website.')
            else:abort(404)
        except Exception as e:flash('Stopped: '+str(e))
        return redirect(url_for('detail',pid=pid))
    @app.get('/history')
    def history():
        with store.db() as c:events=[dict(x) for x in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 250')]
        return render_template('history.html',events=events)
    return app
