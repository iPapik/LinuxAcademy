import asyncio
import hmac
import json
import os
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

from . import storage, labs
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
    return templates.TemplateResponse(request,template,
           {'user':user,'modules':MODULES,'counts':stats(),**ctx})


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
    return RedirectResponse('/dashboard' if user_from_request(request) else '/login',303)


@app.get('/login',response_class=HTMLResponse)
async def login_page(request:Request):
    if user_from_request(request):
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
    guard_csrf(request,user)
    storage.revoke_session(request.cookies.get('lab_session'))
    response=JSONResponse({'ok':True})
    response.delete_cookie('lab_session',path='/')
    return response


@app.get('/dashboard',response_class=HTMLResponse)
async def dashboard(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/login',303)
    done=storage.completed(user['id'])
    total=sum(len(m['lessons']) for m in MODULES)
    return page(request,'dashboard.html',done=done,total=total,
                learned=sum(1 for k,_ in done if k=='lesson'))


@app.get('/lesson/{lesson_id}',response_class=HTMLResponse)
async def lesson(request:Request,lesson_id:str):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/login',303)
    if lesson_id not in LESSONS:
        raise HTTPException(404,'Урок не найден')
    obj=public_lesson(LESSONS[lesson_id])
    done=storage.completed(user['id'])
    all_ids=list(LESSONS)
    idx=all_ids.index(lesson_id)
    return page(request,'lesson.html',lesson=obj,done=done,
                previous=all_ids[idx-1] if idx else None,
                following=all_ids[idx+1] if idx+1<len(all_ids) else None,
                lesson_json=json.dumps(obj,ensure_ascii=False))


@app.get('/reference',response_class=HTMLResponse)
async def reference(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/login',303)
    return page(request,'reference.html',reference=REFERENCE)


@app.get('/lab',response_class=HTMLResponse)
async def lab_page(request:Request,distro:str='ubuntu'):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/login',303)
    if distro not in labs.DISTROS:
        distro='ubuntu'
    return page(request,'lab.html',distros=labs.DISTROS,distro=distro)


@app.get('/admin',response_class=HTMLResponse)
async def admin_page(request:Request):
    user=user_from_request(request)
    if not user:
        return RedirectResponse('/login',303)
    if not user['is_admin']:
        raise HTTPException(403)
    return page(request,'admin.html',users=storage.list_users())


@app.get('/healthz')
async def health():
    return {'status':'ok', 'curriculum':stats()}


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
    return {'ok':True,'passed':passed,'checks':result}


class QuizInput(BaseModel):
    answers: dict[str,str]


@app.post('/api/quiz/{lesson_id}')
async def submit_quiz(request:Request,lesson_id:str,data:QuizInput):
    user=current_user(request); guard_csrf(request,user)
    lesson=LESSONS.get(lesson_id)
    if not lesson:
        raise HTTPException(404)
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
    return {'ok':True,'score':n,'total':len(quiz),'passed':passed,'checks':checks}


class UserCreate(BaseModel):
    username:str
    password:str


@app.post('/api/admin/users')
async def user_create(request:Request,data:UserCreate):
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
