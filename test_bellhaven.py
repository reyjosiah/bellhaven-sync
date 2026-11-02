import copy,json
import pytest
from bellhaven import BASE,API,Store,Reviewer,care,crawl,generate,parse_location,protected,same_place,scan,street
from webapp import create_app

def account(aid='A',**kw):
    return dict(account_id=aid,name='Bellhaven of Test',parent_id='P',parent_name='Bellhaven Senior Living (Parent Account)',billing_street='10 Main St',billing_city='Test',billing_state='OH',billing_zip='12345',care_type='Assisted Living',status='Active',phone='',lifetime_revenue=0,outstanding_ar=0,chow_current_account='',duplicate_of_account='',note='',**{})|kw

def location(**kw):
    return dict(url=BASE+'/communities/test',name='Bellhaven of Test',billing_street='10 Main Street',billing_city='Test',billing_state='OH',billing_zip='12345',care_type='Assisted Living',source_text='Published facility')|kw

def parent():return account('P',name='Bellhaven Senior Living (Parent Account)',parent_id='')
def result(l=None,complete=True):return {'locations':l if l is not None else [location()],'pages':[],'complete':complete,'errors':[]}

class FakeAPI:
    def __init__(self,rows):self.rows={r['account_id']:copy.deepcopy(r) for r in rows};self.writes=[];self.timeout_create=False;self.fail_link=False;self.partial_patch=False
    def all(self):return copy.deepcopy(list(self.rows.values()))
    def get(self,aid):return copy.deepcopy(self.rows[aid])
    def create(self,data):
        self.writes.append(('POST',copy.deepcopy(data)));aid='N'+str(len(self.rows));self.rows[aid]=account(aid,**data)
        if self.timeout_create:raise TimeoutError('simulated create timeout')
        return self.get(aid)
    def patch(self,aid,data):
        self.writes.append(('PATCH',aid,copy.deepcopy(data)))
        if self.fail_link and 'chow_current_account' in data:raise TimeoutError('simulated link failure')
        self.rows[aid].update(data)
        if self.partial_patch:self.rows[aid]['phone']='unexpected'
        return self.get(aid)

def setup(tmp_path,rows,l=None):
    st=Store(tmp_path/'review.db');api=FakeAPI([parent()]+rows);st.save_run(result(l),api.all())
    with st.db() as c:ids=[r[0] for r in c.execute("SELECT id FROM proposals WHERE status='pending'")]
    return st,api,ids

def test_address_and_care():
    assert street('10 North Main Street')==street('10 N Main St.')
    assert care(['Memory Support','Assisted Living','Memory Support'])=='Assisted Living; Memory Care'
    assert same_place(location(),account())

@pytest.mark.parametrize('rev,ar,expected',[(0,0,False),(10,0,False),(0,5,False),(10,5,True)])
def test_billing_branches(rev,ar,expected):assert protected(account(lifetime_revenue=rev,outstanding_ar=ar)) is expected
@pytest.mark.parametrize('value',[None,'','unknown',-1,float('nan'),True])
def test_invalid_money(value):
    with pytest.raises(ValueError):protected(account(lifetime_revenue=value,outstanding_ar=1))

def test_wrong_zip_rename_and_no_address_churn():
    ps,ms,_=generate(result(),[parent(),account(name='Old Name',billing_zip='99999')])
    assert len(ps)==1;assert ps[0]['changes']['name']=='Bellhaven of Test';assert ps[0]['changes']['billing_zip']=='12345';assert 'billing_street' not in ps[0]['changes']

def test_ambiguous_pobox_and_conflict():
    for a in [account(billing_street='PO Box 5'),account(billing_street='20 Other St')]:
        ps,_,_=generate(result(),[parent(),a]);assert ps[0]['kind']=='ambiguous';assert ps[0]['blocked']

def test_duplicate_selection_and_financial_conflict():
    ps,_,_=generate(result(),[parent(),account('A'),account('B',billing_street='10 Main Street',lifetime_revenue=100)])
    dup=next(p for p in ps if p['kind']=='duplicate');assert dup['changes']['duplicate_of_account']=='B';assert dup['changes']['status']=='Inactive'
    ps,_,_=generate(result(),[parent(),account('A',lifetime_revenue=1),account('B',lifetime_revenue=2)])
    assert ps[0]['kind']=='ambiguous'

def test_missing_absent_and_incomplete():
    ps,_,_=generate(result(),[parent()]);assert ps[0]['kind']=='create'
    ps,_,_=generate(result([]),[parent(),account()]);assert ps[0]['kind']=='absent';assert 'parent_id' not in ps[0]['changes']
    ps,_,_=generate(result([],False),[parent(),account()]);assert not ps

def test_pagination_and_bad_page():
    api=API('test-token');api.request=lambda m,p:{'data':[account('A' if 'page=1&' in p else 'B')],'total':2}
    assert len(api.all())==2
    api.request=lambda m,p:{'data':[],'total':2}
    with pytest.raises(ValueError):api.all()

def test_crawl_home_only_and_failure():
    detail='<div class="wrap"><h1>Test</h1><dl><dt>Address</dt><dd>10 Main Street<br>Test, OH 12345</dd><dt>Care Offerings</dt><dd><span class="badge">Assisted Living</span><span class="badge">Memory Support</span></dd></dl></div>'
    pages={BASE+'/':'2 communities and growing <a href="/communities/extra">New</a>',BASE+'/about':'About',BASE+'/communities':'1 communities listed <a href="/communities/test">Test</a><a href="/communities?page=2">Next</a>',BASE+'/communities?page=2':'<a href="/communities/test">Repeated</a>',BASE+'/communities/test':detail,BASE+'/communities/extra':detail}
    r=crawl(lambda u:pages[u]);assert r['complete'];assert len(r['locations'])==2;assert len(r['locations'][0]['offerings'])==2
    del pages[BASE+'/communities/extra'];r=crawl(lambda u:pages[u]);assert not r['complete'];assert r['errors']
    with pytest.raises(ValueError):parse_location('<h1>Broken</h1>','url')

def test_no_writes_rejection_and_second_run(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_zip='99999')]);assert not api.writes
    Reviewer(st,api).reject(ids[0]);st=Store(st.path);st.save_run(result(),api.all());assert st.row(ids[0])['status']=='rejected';assert not api.writes

def test_approve_verify_and_second_run(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_zip='99999')]);Reviewer(st,api).approve(ids[0]);assert api.get('A')['billing_zip']=='12345';assert st.row(ids[0])['status']=='approved'
    _,n=st.save_run(result(),api.all());assert n==0

def test_stale_and_direct_billing_guard(tmp_path):
    st,api,ids=setup(tmp_path,[account(parent_id='OTHER')]);api.rows['A']['outstanding_ar']=1;api.rows['A']['lifetime_revenue']=1
    with pytest.raises(ValueError,match='Stale'):Reviewer(st,api).approve(ids[0])
    assert not api.writes

def test_ownership_preserves_old_and_resumes_link(tmp_path):
    old=account(parent_id='OTHER',lifetime_revenue=100,outstanding_ar=20)
    st,api,ids=setup(tmp_path,[old]);review=Reviewer(st,api)
    with pytest.raises(ValueError,match='Confirm'):review.approve(ids[0])
    api.fail_link=True
    with pytest.raises(TimeoutError):review.approve(ids[0],True)
    assert api.get('A')==old
    api.fail_link=False;review.approve(ids[0],True)
    new_id=api.get('A')['chow_current_account'];assert api.get('A')==old|{'chow_current_account':new_id};assert api.get(new_id)['lifetime_revenue']==0
    assert len([w for w in api.writes if w[0]=='POST'])==1
    _,n=st.save_run(result(),api.all());assert n==0

def test_uncertain_create_reconciles_without_duplicate(tmp_path):
    st,api,ids=setup(tmp_path,[]);api.timeout_create=True
    with pytest.raises(TimeoutError):Reviewer(st,api).approve(ids[0])
    Reviewer(st,api).approve(ids[0]);assert len([w for w in api.writes if w[0]=='POST'])==1

def test_uncertain_create_with_no_marker_stops(tmp_path):
    st,api,ids=setup(tmp_path,[])
    def fail(data):raise TimeoutError('before create')
    api.create=fail
    with pytest.raises(TimeoutError):Reviewer(st,api).approve(ids[0])
    with pytest.raises(ValueError,match='uncertain'):Reviewer(st,api).approve(ids[0])
    assert len(api.rows)==1

def test_unexpected_field_change_fails_verification(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_zip='99999')]);api.partial_patch=True
    with pytest.raises(ValueError,match='verification'):Reviewer(st,api).approve(ids[0])

def test_web_csrf_get_no_write_and_confirmation(tmp_path):
    st,api,ids=setup(tmp_path,[account(parent_id='OTHER',lifetime_revenue=10,outstanding_ar=2)])
    app=create_app(st,api);app.testing=True;client=app.test_client()
    assert client.get('/').status_code==200;assert client.get('/proposal/'+ids[0]).status_code==200;assert not api.writes
    assert client.post('/proposal/'+ids[0]+'/approve').status_code==403
    with client.session_transaction() as s:csrf=s['csrf']
    client.post('/proposal/'+ids[0]+'/approve',data={'csrf':csrf});assert not api.writes
    assert client.post('/proposal/'+ids[0]+'/approve',data={'csrf':csrf,'confirmed':'yes'},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/',headers={'Host':'evil.example'}).status_code==400


def test_review_candidate_selection_no_write(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_street='PO Box 5')]);app=create_app(st,api);app.testing=True;client=app.test_client();client.get('/')
    with client.session_transaction() as s:csrf=s['csrf']
    response=client.post('/proposal/'+ids[0]+'/resolve',data={'csrf':csrf,'account_id':'A','reason':'Exact name and city; billing address is a PO box.'})
    assert response.status_code==302;assert not api.writes;assert st.row(ids[0])['status']=='resolved'
    st.save_run(result(),api.all());assert st.row(ids[0])['status']=='resolved'

def test_invalid_ar_even_without_revenue():
    with pytest.raises(ValueError):protected(account(lifetime_revenue=0,outstanding_ar=None))

def test_new_match_blocks_creation(tmp_path):
    st,api,ids=setup(tmp_path,[]);api.rows['EXTERNAL']=account('EXTERNAL')
    with pytest.raises(ValueError,match='potential match'):Reviewer(st,api).approve(ids[0])
    assert not api.writes

def test_selection_correction_survives_rescan(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_street='PO Box 5')]);app=create_app(st,api);client=app.test_client();client.get('/')
    with client.session_transaction() as s:csrf=s['csrf']
    response=client.post('/proposal/'+ids[0]+'/resolve',data={'csrf':csrf,'account_id':'A','reason':'Same name and city, different billing address.'})
    nid=response.headers['Location'].split('/')[-1]
    st.save_run(result(),api.all());assert st.row(nid)['status']=='pending'
    Reviewer(st,api).approve(nid);_,n=st.save_run(result(),api.all());assert n==0

def test_all_routes_escape_evidence_and_preview_creation_marker(tmp_path):
    st,api,ids=setup(tmp_path,[],[location(name='<script>alert(1)</script>')]);app=create_app(st,api);app.testing=True;client=app.test_client()
    for route in ['/', '/history', '/proposal/'+ids[0], '/?status=&kind=create']:
        r=client.get(route);assert r.status_code==200;assert b'<script>alert(1)</script>' not in r.data
    assert ('[proposal:'+ids[0]+']').encode() in client.get('/proposal/'+ids[0]).data
    assert not api.writes

def test_verify_api_error_never_approved(tmp_path):
    st,api,ids=setup(tmp_path,[account(billing_zip='99999')])
    def failure(aid,data):raise RuntimeError('HTTP 422')
    api.patch=failure
    with pytest.raises(RuntimeError):Reviewer(st,api).approve(ids[0])
    assert st.row(ids[0])['status']=='error'

def test_duplicate_suppression_and_absence_flag_rerun(tmp_path):
    st,api,ids=setup(tmp_path,[account('A'),account('B')]);dup=next(pid for pid in ids if json.loads(st.row(pid)['payload'])['kind']=='duplicate')
    Reviewer(st,api).approve(dup);_,n=st.save_run(result(),api.all());assert n==0
    st2=Store(tmp_path/'absent.db');api2=FakeAPI([parent(),account()]);st2.save_run(result([]),api2.all())
    with st2.db() as c:pid=c.execute('SELECT id FROM proposals').fetchone()[0]
    Reviewer(st2,api2).approve(pid);_,n=st2.save_run(result([]),api2.all());assert n==0
