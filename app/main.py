import asyncio
import hmac
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

try:
    import markdown
except ImportError:  # Allows offline source checks where only mistune is installed.
    import mistune
    class markdown:
        @staticmethod
        def markdown(value, extensions=None):
            return mistune.html(value)
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import storage, labs, achievements, learning_path
from .curriculum import MODULES, LESSONS, TASKS, public_lesson, stats
REFERENCE = (Path(__file__).resolve().parent.parent / "content" / "reference.md").read_text(encoding="utf-8")

BASE = Path(__file__).resolve().parent.parent
storage.init_db()
app=FastAPI(title='LinuxAcademy',docs_url=None,redoc_url=None,openapi_url=None)
app.mount('/static', StaticFiles(directory=BASE/'static'),name='static')
templates=Jinja2Templates(directory=BASE/'templates')
templates.env.filters['md']=lambda value: markdown.markdown(value,extensions=['fenced_code','tables','sane_lists'])
LOGIN_EVENTS=defaultdict(deque)
LAB_LOCKS=defaultdict(asyncio.Lock)
MAX_WS_PER_USER=2
ACTIVE_WS=defaultdict(int)
SECURE_COOKIE=os.environ.get('ACADEMY_SECURE_COOKIE','1') == '1'
GUEST_MODE=os.environ.get('ACADEMY_GUEST_MODE','0') == '1'
GUEST_EVENTS=defaultdict(deque)
SIGNUP_EVENTS=defaultdict(deque)


@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']=(
       "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self' ws: wss:; font-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
    response.headers['Cache-Control']='no-store'
    return response


def user_from_request(request):
    return storage.get_session(request.cookies.get('lab_session'))


def page(request,template,**ctx):
    user=user_from_request(request)
    done=storage.completed(user['id']) if user else set()
    return templates.TemplateResponse(request,template,
           {'user':user,'guest_mode':GUEST_MODE,'modules':MODULES,'counts':stats(),
            'unlocked_lessons':learning_path.unlocked_lessons(done),
            'module_progress':learning_path.module_state(done),
            'next_lesson_id':learning_path.next_lesson(done),
            'progress_done':done, **ctx})


def require_open_lesson(lesson_id, done):
    if not learning_path.is_unlocked(lesson_id, done):
        required=learning_path.prerequisite(lesson_id, done)
        title=LESSONS[required]['title'] if required else 'предыдущий урок'
        raise HTTPException(
            403, f'Урок заблокирован. Сначала завершите предыдущий урок: {title}')


def locked_lesson_page(request, lesson_id, done):
    required=learning_path.prerequisite(lesson_id, done)
    response=page(request,'locked.html',target=LESSONS[lesson_id],
                  required=LESSONS[required] if required else None)
    response.status_code=403
    return response


def current_user(request):
    user=user_from_request(request)
    if not user:
        raise HTTPException(401,'Войдите в систему')
    return user


def guard_csrf(request,user):
    if not hmac.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
        raise HTTPException(403,'Некорректный CSRF-токен')
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403,'Неверный Origin')


def payload_error(msg,status=400):
    return JSONResponse({'ok':False,'error':msg},status_code=status)


@app.get('/',include_in_schema=False)
async def index(request:Request):
    if user_from_request(request):
        return RedirectResponse('/dashboard',303)
    if not GUEST_MODE:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    ip=request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    now=time.monotonic()
    bucket=GUEST_EVENTS[ip]
    while bucket and now-bucket[0]>3600:
        bucket.popleft()
    if len(bucket)>=20:
        raise HTTPException(429,'Слишком много новых учебных профилей с этого адреса')
    token=storage.create_guest_session()
    bucket.append(now)
    destination='/register' if request.query_params.get('next')=='register' else '/dashboard'
    response=RedirectResponse(destination,303)
    response.set_cookie('lab_session',token,max_age=storage.GUEST_SESSION_AGE,
                        httponly=True,secure=SECURE_COOKIE,samesite='lax',path='/')
    return response


@app.get('/login',response_class=HTMLResponse)
async def login_page(request:Request):
    if GUEST_MODE:
        if user_from_request(request) and not user_from_request(request).get('is_guest'):
            return RedirectResponse('/profile',303)
    elif user_from_request(request):
        return RedirectResponse('/dashboard',303)
    return page(request,'login.html',error=None)


@app.post('/login')
async def login(request:Request):
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        return page(request,'login.html',error='Неверный источник запроса')
    form=await request.form()
    username=str(form.get('username','')).strip().lower()[:50]
    password=str(form.get('password',''))
    # nginx binds the application to loopback and overwrites X-Real-IP with the client IP.
    ip=request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    now=time.monotonic()
    bucket=LOGIN_EVENTS[ip]
    while bucket and now-bucket[0]>300:
        bucket.popleft()
    if len(bucket)>=10:
        return page(request,'login.html',error='Слишком много попыток. Попробуйте через 5 минут.')
    user=storage.authenticate(username,password)
    if not user:
        bucket.append(now)
        return page(request,'login.html',error='Неправильный логин или пароль')
    bucket.clear()
    token=storage.create_session(user['id'])
    response=RedirectResponse('/dashboard',303)
    response.set_cookie('lab_session',token,max_age=storage.SESSION_AGE,
       httponly=True,secure=SECURE_COOKIE,samesite='lax',path='/')
    return response


@app.post('/logout')
async def logout(request:Request):
    user=current_user(request)
    if user.get('is_guest'):
        raise HTTPException(403,'Сначала зарегистрируйте учебный профиль')
    guard_csrf(request,user)
    storage.revoke_session(request.cookies.get('lab_session'))
    response=JSONResponse({'ok':True})
    response.delete_cookie('lab_session',path='/')
    return response


@app.get('/dashboard',response_class=HTMLResponse)
async def dashboard(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    done=storage.completed(user['id'])
    total=sum(len(m['lessons']) for m in MODULES)
    return page(request,'dashboard.html',done=done,total=total,
                current_lesson=LESSONS[learning_path.next_lesson(done)] if learning_path.next_lesson(done) else None,
                awards=achievements.snapshot(user),
                learned=sum(1 for k,_ in done if k=='lesson'))


@app.get('/lesson/{lesson_id}',response_class=HTMLResponse)
async def lesson(request:Request,lesson_id:str):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    if lesson_id not in LESSONS:
        raise HTTPException(404,'Урок не найден')
    done=storage.completed(user['id'])
    if not learning_path.is_unlocked(lesson_id, done):
        return locked_lesson_page(request,lesson_id,done)
    obj=public_lesson(LESSONS[lesson_id])
    all_ids=list(LESSONS)
    idx=all_ids.index(lesson_id)
    return page(request,'lesson.html',lesson=obj,done=done,
                has_read=(('read',lesson_id) in done or ('lesson',lesson_id) in done or ('quiz',lesson_id) in done),
                quiz_passed=(('quiz',lesson_id) in done or ('lesson',lesson_id) in done),
                previous=all_ids[idx-1] if idx else None,
                following=all_ids[idx+1] if idx+1<len(all_ids) else None,
                following_unlocked=(idx+1<len(all_ids) and learning_path.is_unlocked(all_ids[idx+1],done)),
                lesson_json=json.dumps(obj,ensure_ascii=False))



@app.get('/register',response_class=HTMLResponse)
async def register_page(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/?next=register' if GUEST_MODE else '/login',303)
    if not user.get('is_guest'):
        return RedirectResponse('/profile',303)
    return page(request,'register.html',error=None)


@app.post('/register')
async def register_account(request:Request):
    user=current_user(request)
    if not user.get('is_guest'):
        return RedirectResponse('/profile',303)
    form=await request.form()
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403,'Некорректный источник')
    if not hmac.compare_digest(str(form.get('csrf','')),user['csrf']):
        raise HTTPException(403,'Некорректный CSRF-токен')
    ip=request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    now=time.monotonic(); bucket=SIGNUP_EVENTS[ip]
    while bucket and now-bucket[0]>3600:
        bucket.popleft()
    if len(bucket)>=10:
        raise HTTPException(429,'Превышен лимит регистраций с этого адреса')
    username=str(form.get('username','')).strip().lower()
    password=str(form.get('password',''))
    confirm=str(form.get('confirm',''))
    if password!=confirm:
        return page(request,'register.html',error='Пароли не совпадают')
    try:
        uid=storage.register(username,password,guest_user_id=user['id'])
    except ValueError as exc:
        return page(request,'register.html',error=str(exc))
    except sqlite3.IntegrityError:
        return page(request,'register.html',error='Это имя пользователя занято')
    bucket.append(now)
    token=storage.create_session(uid)
    response=RedirectResponse('/profile',303)
    response.set_cookie('lab_session',token,max_age=storage.SESSION_AGE,
                        httponly=True,secure=SECURE_COOKIE,samesite='lax',path='/')
    return response


@app.get('/profile',response_class=HTMLResponse)
async def profile_page(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    return page(request,'profile.html',awards=achievements.snapshot(user))


@app.post('/api/lesson/{lesson_id}/read')
async def mark_lesson_read(request:Request,lesson_id:str):
    user=current_user(request)
    guard_csrf(request,user)
    if lesson_id not in LESSONS:
        raise HTTPException(404,'Урок не найден')
    require_open_lesson(lesson_id,storage.completed(user['id']))
    storage.complete(user['id'],'read',lesson_id)
    return {'ok':True,'lesson':lesson_id}


@app.get('/reference',response_class=HTMLResponse)
async def reference(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    return page(request,'reference.html',reference=REFERENCE)


@app.get('/lab',response_class=HTMLResponse)
async def lab_page(request:Request,distro:str='ubuntu'):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    if distro not in labs.DISTROS:
        distro='ubuntu'
    return page(request,'lab.html',distros=labs.DISTROS,distro=distro)


@app.get('/admin',response_class=HTMLResponse)
async def admin_page(request:Request):
    if GUEST_MODE:
        raise HTTPException(403,'Управление пользователями отключено')
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/' if GUEST_MODE else '/login',303)
    if not user['is_admin']:
        raise HTTPException(403)
    return page(request,'admin.html',users=storage.list_users())


@app.get('/healthz')
async def health():
    return {'status':'ok', 'release':'1.3.0', 'curriculum':stats()}


@app.get('/robots.txt')
async def robots():
    return PlainTextResponse('User-agent: *\nDisallow: /\n')


class DistroInput(BaseModel):
    distro: str = 'ubuntu'


@app.post('/api/lab/start')
async def start_lab(request:Request,data:DistroInput):
    user=current_user(request); guard_csrf(request,user)
    if data.distro not in labs.DISTROS:
        return payload_error('Неизвестная ОС')
    async with LAB_LOCKS[user['id']]:
        try:
            name=await asyncio.to_thread(labs.ensure_lab,user['id'],data.distro)
            return {'ok':True,'name':name,'distro':data.distro}
        except RuntimeError as exc:
            return payload_error(str(exc),503)


@app.post('/api/lab/reset')
async def reset_lab(request:Request,data:DistroInput):
    user=current_user(request); guard_csrf(request,user)
    if data.distro not in labs.DISTROS:
        return payload_error('Неизвестная ОС')
    if ACTIVE_WS[user['id']]:
        return payload_error('Сначала закройте открытые терминалы')
    async with LAB_LOCKS[user['id']]:
        try:
            name=await asyncio.to_thread(labs.reset_lab,user['id'],data.distro)
            return {'ok':True,'name':name}
        except RuntimeError as exc:
            return payload_error(str(exc),503)


@app.post('/api/task/{task_id}/prepare')
async def task_prepare(request:Request,task_id:str):
    user=current_user(request); guard_csrf(request,user)
    task=TASKS.get(task_id)
    if not task:
        raise HTTPException(404)
    task_done=storage.completed(user['id'])
    require_open_lesson(task['lesson_id'],task_done)
    if ('quiz',task['lesson_id']) not in task_done and ('lesson',task['lesson_id']) not in task_done:
        raise HTTPException(403,'Сначала сдайте тест по теории')
    async with LAB_LOCKS[user['id']]:
        try:
            name=await asyncio.to_thread(labs.ensure_lab,user['id'],task['distro'])
            await asyncio.to_thread(labs.prepare_task,name,task)
            return {'ok':True,'distro':task['distro']}
        except RuntimeError as exc:
            return payload_error(str(exc),503)


def update_lesson_completion(user_id,lesson_id):
    done=storage.completed(user_id)
    lesson=LESSONS[lesson_id]
    if ('quiz',lesson_id) in done and all(('task',t['id']) in done for t in lesson.get('tasks',[])):
        storage.complete(user_id,'lesson',lesson_id)


@app.post('/api/task/{task_id}/verify')
async def task_verify(request:Request,task_id:str):
    user=current_user(request); guard_csrf(request,user)
    task=TASKS.get(task_id)
    if not task:
        raise HTTPException(404)
    task_done=storage.completed(user['id'])
    require_open_lesson(task['lesson_id'],task_done)
    if ('quiz',task['lesson_id']) not in task_done and ('lesson',task['lesson_id']) not in task_done:
        raise HTTPException(403,'Сначала сдайте тест по теории')
    async with LAB_LOCKS[user['id']]:
        try:
            name=await asyncio.to_thread(labs.ensure_lab,user['id'],task['distro'])
            result=await asyncio.to_thread(labs.check_task,name,task)
        except RuntimeError as exc:
            return payload_error(str(exc),503)
    passed=all(r['ok'] for r in result)
    if passed:
        storage.complete(user['id'],'task',task_id)
        update_lesson_completion(user['id'],task['lesson_id'])
    return {'ok':True,'passed':passed,'checks':result,
            'lesson_completed':('lesson',task['lesson_id']) in storage.completed(user['id'])}


class QuizInput(BaseModel):
    answers: dict[str,str]


@app.post('/api/quiz/{lesson_id}')
async def submit_quiz(request:Request,lesson_id:str,data:QuizInput):
    user=current_user(request); guard_csrf(request,user)
    lesson=LESSONS.get(lesson_id)
    if not lesson:
        raise HTTPException(404)
    done=storage.completed(user['id'])
    require_open_lesson(lesson_id,done)
    if ('read',lesson_id) not in done and ('quiz',lesson_id) not in done and ('lesson',lesson_id) not in done:
        raise HTTPException(403,'Сначала изучите теорию урока')
    quiz=lesson.get('quiz',[])
    if not quiz:
        raise HTTPException(400,'В уроке нет теста')
    checks=[]
    for q in quiz:
        value=data.answers.get(q['id'],'')
        checks.append({'id':q['id'],'passed':value==q['answer'],'correct':q['answer'],
                       'explanation':q['explanation']})
    n=sum(c['passed'] for c in checks)
    storage.record_attempt(user['id'],lesson_id,n,len(quiz))
    passed=n*100>=70*len(quiz)
    if passed:
        storage.complete(user['id'],'quiz',lesson_id)
        update_lesson_completion(user['id'],lesson_id)
    return {'ok':True,'score':n,'total':len(quiz),'passed':passed,'checks':checks,
            'lesson_completed':('lesson',lesson_id) in storage.completed(user['id'])}


class UserCreate(BaseModel):
    username:str
    password:str


@app.post('/api/admin/users')
async def user_create(request:Request,data:UserCreate):
    if GUEST_MODE:
        raise HTTPException(403,'Управление пользователями отключено')
    user=current_user(request); guard_csrf(request,user)
    if not user['is_admin']:
        raise HTTPException(403)
    try:
        storage.add_user(data.username.lower(),data.password)
        return {'ok':True}
    except ValueError as exc:
        return payload_error(str(exc))
    except Exception as exc:
        if 'UNIQUE constraint failed' in str(exc):
            return payload_error('Пользователь уже существует')
        raise


@app.post('/api/admin/users/{user_id}/password')
async def user_password(request:Request,user_id:int,data:UserCreate):
    if GUEST_MODE:
        raise HTTPException(403,'Управление пользователями отключено')
    user=current_user(request); guard_csrf(request,user)
    if not user['is_admin']:
        raise HTTPException(403)
    try:
        storage.reset_password(user_id,data.password)
        return {'ok':True}
    except ValueError as exc:
        return payload_error(str(exc))


@app.websocket('/ws/{distro}')
async def terminal_ws(ws:WebSocket,distro:str):
    session=storage.get_session(ws.cookies.get('lab_session'))
    origin=ws.headers.get('origin','')
    if (not session or distro not in labs.DISTROS or not origin or
            urlparse(origin).netloc != ws.headers.get('host')):
        await ws.close(code=1008)
        return
    uid=session['id']
    if ACTIVE_WS[uid]>=MAX_WS_PER_USER:
        await ws.close(code=1013)
        return
    ACTIVE_WS[uid]+=1
    terminal=None
    try:
        await ws.accept()
        async with LAB_LOCKS[uid]:
            name=await asyncio.to_thread(labs.ensure_lab,uid,distro)
        terminal=labs.Terminal(name,distro)
        await terminal.start()
        async def stream_out():
            while True:
                data=await terminal.read()
                if not data:
                    break
                await ws.send_bytes(data)
        async def stream_in():
            while True:
                item=await ws.receive()
                if item['type']=='websocket.disconnect':
                    break
                if item.get('bytes'):
                    await terminal.write(item['bytes'].decode(errors='replace'))
                elif item.get('text'):
                    message=json.loads(item['text'])
                    if message.get('type')=='resize':
                        terminal.resize(message.get('cols',80),message.get('rows',24))
                    elif message.get('type')=='input':
                        await terminal.write(str(message.get('data',''))[:8192])
        outgoing=asyncio.create_task(stream_out())
        incoming=asyncio.create_task(stream_in())
        done,pending=await asyncio.wait([incoming,outgoing],return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
    except Exception as exc:
        # A recoverable error is displayed in the browser if the socket is still open.
        try:
            await ws.send_text(json.dumps({'type':'error','message':str(exc)[:500]}))
        except Exception:
            pass
    finally:
        if terminal:
            await terminal.stop()
        ACTIVE_WS[uid]=max(0,ACTIVE_WS[uid]-1)
        try:
            await ws.close()
        except Exception:
            pass
