import os
import tempfile
from pathlib import Path

# Keep test-generated accounts out of the distributable application directory.
os.environ['ACADEMY_DATA_DIR']=tempfile.mkdtemp(prefix='linuxacademy-test-')
os.environ['ACADEMY_SECURE_COOKIE']='0'

from fastapi.testclient import TestClient
from app import storage
from app.curriculum import MODULES,LESSONS,TASKS,stats,public_lesson
from app.main import app
from app import labs


def auth(client,username,password):
    r=client.post('/login',data={'username':username,'password':password},follow_redirects=False)
    assert r.status_code==303
    assert client.cookies.get('lab_session')
    return storage.get_session(client.cookies.get('lab_session'))


def test_content_is_complete_and_checkers_private():
    s=stats()
    assert s == {'modules':14,'lessons':76,'tasks':78,'questions':152}
    assert len(set(LESSONS)) == len(LESSONS)
    assert len(set(TASKS)) == len(TASKS)
    assert all(len(l['quiz'])>=2 for l in LESSONS.values())
    assert all(len(q['options'])==4 and q['answer'] in '0123' for l in LESSONS.values() for q in l['quiz'])
    for l in LESSONS.values():
        p=public_lesson(l)
        assert all('answer' not in q for q in p['quiz'])
        assert all('checks' not in t and 'setup' not in t for t in p['tasks'])


def test_login_role_csrf_quiz_and_progress(monkeypatch):
    storage.init_db()
    storage.add_user('mainadmin','ATestingPasswordNotForProd!',admin=True)
    storage.add_user('student1','AnotherTestPass1234!')
    with TestClient(app) as c:
        assert c.get('/dashboard',follow_redirects=False).status_code==303
        assert c.post('/login',data={'username':'student1','password':'wrong'},follow_redirects=False).status_code==200
        user=auth(c,'student1','AnotherTestPass1234!')
        assert c.get('/dashboard').status_code==200
        assert c.get('/lesson/m02-l01').status_code==200
        assert c.get('/admin').status_code==403
        assert c.post('/api/lab/start',json={'distro':'ubuntu'}).status_code==403
        csrf={'X-CSRF-Token':user['csrf']}
        assert c.post('/api/lab/start',json={'distro':'hacker'},headers=csrf).status_code==400
        monkeypatch.setattr(labs,'ensure_lab',lambda uid,distro:'mock-container')
        monkeypatch.setattr(labs,'prepare_task',lambda name,task:None)
        monkeypatch.setattr(labs,'check_task',lambda name,task:[{'description':'mock','ok':True}])
        assert c.post('/api/task/m02-l01-p1/prepare',headers=csrf).json()['ok']
        assert c.post('/api/task/m02-l01-p1/verify',headers=csrf).json()['passed']
        q=LESSONS['m02-l01']['quiz']
        r=c.post('/api/quiz/m02-l01',headers=csrf,json={'answers':{x['id']:x['answer'] for x in q}})
        assert r.json()['passed']
        assert ('lesson','m02-l01') not in storage.completed(user['id'])
        c.post('/api/task/m02-l01-p2/verify',headers=csrf)
        assert ('lesson','m02-l01') in storage.completed(user['id'])
        assert c.post('/logout',headers=csrf).json()['ok']
        assert c.get('/dashboard',follow_redirects=False).status_code==303
    with TestClient(app) as a:
        admin=auth(a,'mainadmin','ATestingPasswordNotForProd!')
        csrf={'X-CSRF-Token':admin['csrf']}
        assert a.get('/admin').status_code==200
        assert a.post('/api/admin/users',json={'username':'newstudent','password':'LongPassword1234567!'},headers=csrf).json()['ok']
        assert storage.authenticate('newstudent','LongPassword1234567!')
        assert a.post('/api/admin/users',json={'username':'bad name','password':'LongPassword1234567!'},headers=csrf).status_code==400


def test_lab_names_not_controlled_by_untrusted_input():
    assert labs.name_for(12,'ubuntu')=='linuxacademy-u12-ubuntu'
    for invalid in ['../../root','foo;rm -rf /','', 'Ubuntu']:
        try:labs.name_for(12,invalid)
        except ValueError:pass
        else:assert False


def test_passwordless_guest_mode_keeps_separate_progress_and_blocks_admin(monkeypatch):
    # Enabled by the on-prem installer, unlike the optional legacy auth mode.
    from app import main as app_main
    monkeypatch.setattr(app_main,'GUEST_MODE',True)
    app_main.GUEST_EVENTS.clear()
    with TestClient(app) as first, TestClient(app) as second:
        r=first.get('/',follow_redirects=False)
        assert r.status_code==303
        assert r.headers['location']=='/dashboard'
        one=storage.get_session(first.cookies.get('lab_session'))
        assert one and not one['is_admin'] and one['username'].startswith('guest-')
        assert first.get('/dashboard').status_code==200
        assert first.get('/lesson/m02-l01').status_code==200
        assert first.get('/reference').status_code==200
        assert first.get('/lab').status_code==200
        assert first.get('/admin').status_code==403
        assert first.get('/login',follow_redirects=False).status_code==200
        assert first.post('/login',data={'username':'mainadmin','password':'wrong'}).status_code==200
        assert first.post('/api/admin/users',json={'username':'hacker','password':'PasswordLong12345'}).status_code==403
        two_r=second.get('/',follow_redirects=False)
        assert two_r.status_code==303
        two=storage.get_session(second.cookies.get('lab_session'))
        assert two['id']!=one['id']
        assert first.cookies.get('lab_session')!=second.cookies.get('lab_session')
        quiz=LESSONS['m02-l01']['quiz']
        result=first.post('/api/quiz/m02-l01',
            headers={'X-CSRF-Token':one['csrf']},
            json={'answers':{q['id']:q['answer'] for q in quiz}})
        assert result.json()['passed']
        assert ('quiz','m02-l01') in storage.completed(one['id'])
        assert ('quiz','m02-l01') not in storage.completed(two['id'])
        assert first.post('/logout',headers={'X-CSRF-Token':one['csrf']}).status_code==403
        assert first.get('/').status_code==200
