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
        assert c.get('/lesson/m00-l01').status_code==200
        assert c.get('/lesson/m02-l01').status_code==403
        # Complete earlier lessons to reach a legacy two-task lesson.
        from app import learning_path
        for previous in learning_path.ORDER[:learning_path.INDEX['m02-l01']]:
            storage.complete(user['id'],'lesson',previous)
        assert c.get('/lesson/m02-l01').status_code==200
        assert c.get('/admin').status_code==403
        assert c.post('/api/lab/start',json={'distro':'ubuntu'}).status_code==403
        csrf={'X-CSRF-Token':user['csrf']}
        assert c.post('/api/lab/start',json={'distro':'hacker'},headers=csrf).status_code==400
        monkeypatch.setattr(labs,'ensure_lab',lambda uid,distro:'mock-container')
        monkeypatch.setattr(labs,'prepare_task',lambda name,task:None)
        monkeypatch.setattr(labs,'check_task',lambda name,task:[{'description':'mock','ok':True}])
        assert c.post('/api/task/m02-l01-p1/prepare',headers=csrf).status_code==403
        assert c.post('/api/lesson/m02-l01/read',headers=csrf).json()['ok']
        q=LESSONS['m02-l01']['quiz']
        r=c.post('/api/quiz/m02-l01',headers=csrf,json={'answers':{x['id']:x['answer'] for x in q}})
        assert r.json()['passed']
        assert c.post('/api/task/m02-l01-p1/prepare',headers=csrf).json()['ok']
        assert c.post('/api/task/m02-l01-p1/verify',headers=csrf).json()['passed']
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
        assert first.get('/lesson/m00-l01').status_code==200
        assert first.get('/lesson/m02-l01').status_code==403
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
        quiz=LESSONS['m00-l01']['quiz']
        assert first.post('/api/lesson/m00-l01/read',headers={'X-CSRF-Token':one['csrf']}).status_code==200
        result=first.post('/api/quiz/m00-l01',
            headers={'X-CSRF-Token':one['csrf']},
            json={'answers':{q['id']:q['answer'] for q in quiz}})
        assert result.json()['passed']
        assert ('quiz','m00-l01') in storage.completed(one['id'])
        assert ('quiz','m00-l01') not in storage.completed(two['id'])
        assert first.post('/logout',headers={'X-CSRF-Token':one['csrf']}).status_code==403
        assert first.get('/').status_code==200


def test_foundation_progression_and_persistent_badges(monkeypatch):
    from app import main as app_main, achievements
    monkeypatch.setattr(app_main, 'GUEST_MODE', True)
    with TestClient(app) as c:
        c.get('/')
        guest=storage.get_session(c.cookies.get('lab_session'))
        csrf={'X-CSRF-Token':guest['csrf']}
        assert c.post('/api/quiz/m00-l01',headers=csrf,json={'answers':{}}).status_code==403
        assert c.post('/api/task/m00-l01-p1/prepare',headers=csrf).status_code==403
        assert c.post('/api/lesson/m00-l01/read',headers=csrf).json()['ok']
        assert c.get('/lesson/m00-l01').status_code==200
        q=LESSONS['m00-l01']['quiz']
        assert c.post('/api/quiz/m00-l01',headers=csrf,
            json={'answers':{item['id']:item['answer'] for item in q}}).json()['passed']
        first=achievements.snapshot(guest)
        assert any(b['id']=='first_quiz' and b['earned'] for b in first['badges'])
        again=achievements.snapshot(guest)
        assert again['earned']==first['earned']
        assert again['xp']==first['xp']


def test_guest_to_registered_profile_survives_restart_and_logout(monkeypatch):
    from app import main as app_main, achievements
    monkeypatch.setattr(app_main, 'GUEST_MODE', True)
    with TestClient(app) as browser:
        assert browser.get('/', follow_redirects=False).status_code == 303
        visitor=storage.get_session(browser.cookies.get('lab_session'))
        assert visitor['is_guest']
        assert browser.get('/dashboard').status_code == 200
        assert browser.get('/profile').status_code == 200
        assert browser.get('/register').status_code == 200
        storage.complete(visitor['id'], 'read', 'm00-l01')
        form={'csrf':visitor['csrf'], 'username':'academytester',
              'password':'ThisIsATestOnly12345', 'confirm':'ThisIsATestOnly12345'}
        response=browser.post('/register',data=form,follow_redirects=False)
        assert response.status_code == 303
        registered=storage.get_session(browser.cookies.get('lab_session'))
        assert registered['id'] == visitor['id']
        assert not registered['is_guest']
        assert registered['username'] == 'academytester'
        assert ('read','m00-l01') in storage.completed(registered['id'])
        assert browser.get('/profile').status_code == 200
        assert browser.get('/dashboard').status_code == 200
        earned=achievements.snapshot(registered)
        assert any(b['id']=='registered' and b['earned'] for b in earned['badges'])
        assert browser.post('/logout',headers={'X-CSRF-Token':registered['csrf']}).json()['ok']
    with TestClient(app) as second:
        login=second.post('/login',data={'username':'academytester',
                    'password':'ThisIsATestOnly12345'},follow_redirects=False)
        assert login.status_code==303
        again=storage.get_session(second.cookies.get('lab_session'))
        assert again['id']==visitor['id']
        assert second.get('/profile').status_code==200


def test_first_visit_register_route_and_extended_reading(monkeypatch):
    from app import main as app_main
    monkeypatch.setattr(app_main, 'GUEST_MODE', True)
    with TestClient(app) as c:
        response = c.get('/register')
        assert response.status_code == 200
        assert 'Регистрация' in response.text
        assert c.get('/profile').status_code == 200
        assert c.get('/dashboard').status_code == 200
        assert c.get('/lesson/m00-l02').status_code==403
        assert c.get('/lesson/m13-l01').status_code==403
        visitor=storage.get_session(c.cookies.get('lab_session'))
        from app import learning_path
        for previous in learning_path.ORDER[:learning_path.INDEX['m13-l01']]:
            storage.complete(visitor['id'],'lesson',previous)
        basics=c.get('/lesson/m00-l02')
        assert basics.status_code==200
        assert 'Подробный учебник' in basics.text
        assert 'Файловая система' in basics.text
        storage_lesson=c.get('/lesson/m13-l01')
        assert storage_lesson.status_code==200
        assert 'Btrfs' in storage_lesson.text
        assert 'XFS' in storage_lesson.text


def test_existing_database_receives_achievements_table(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path/'academy.sqlite3')
    with storage.connect() as conn:
        conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
        conn.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES('previousstudent','legacy',0,1)")
    storage.init_db()
    with storage.connect() as conn:
        assert conn.execute("SELECT username FROM users WHERE username='previousstudent'").fetchone()[0]=='previousstudent'
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='achievements'").fetchone()[0]=='achievements'
