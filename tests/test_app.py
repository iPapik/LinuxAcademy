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
    assert s == {'modules':11,'lessons':47,'tasks':49,'questions':94}
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
