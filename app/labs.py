"""Isolated, per-user Podman laboratories. Never constructs host shell strings."""
import asyncio
import fcntl
import os
import pty
import re
import signal
import struct
import subprocess
import termios

DISTROS = {
 'ubuntu': {'name':'Ubuntu 24.04 LTS', 'image':'localhost/linuxacademy-ubuntu:24.04', 'shell':'/bin/bash'},
 'debian': {'name':'Debian 13 (Trixie)', 'image':'localhost/linuxacademy-debian:13', 'shell':'/bin/bash'},
 'alma': {'name':'AlmaLinux 9', 'image':'localhost/linuxacademy-alma:9', 'shell':'/bin/bash'},
}


def name_for(user_id, distro):
    if distro not in DISTROS:
        raise ValueError('Неизвестный дистрибутив')
    return f'linuxacademy-u{int(user_id)}-{distro}'


def command(*args, timeout=45):
    try:
        return subprocess.run(['podman', *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Podman недоступен: {exc}') from exc


def ready(name):
    p = command('inspect', '--format', '{{.State.Running}}', name)
    return p.returncode == 0 and p.stdout.strip() == 'true'


def ensure_lab(user_id, distro):
    name = name_for(user_id, distro)
    if ready(name):
        return name
    existing = command('container','exists',name)
    if existing.returncode == 0:
        p = command('start', name)
    else:
        p = command('run','-d','--name',name,'--network=none','--cap-drop=ALL',
          '--cap-add=CHOWN','--cap-add=FOWNER','--cap-add=SETUID','--cap-add=SETGID',
          '--security-opt=no-new-privileges','--pids-limit=128','--memory=768m',
          '--cpus=1','--tmpfs=/tmp:rw,nosuid,size=64m','--workdir=/workspace',
          DISTROS[distro]['image'], 'sleep','infinity',timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:800] or 'Ошибка запуска лаборатории')
    return name


def reset_lab(user_id, distro):
    name = name_for(user_id,distro)
    command('rm','-f',name,timeout=30)
    return ensure_lab(user_id,distro)


def exec_script(name, script, timeout=12):
    # Script text comes exclusively from bundled trusted curriculum, not from a visitor.
    return command('exec',name,'/bin/bash','-c',script,timeout=timeout)


def prepare_task(name, task):
    if task.get('setup'):
        p=exec_script(name, task['setup'])
        if p.returncode != 0:
            raise RuntimeError('Не удалось подготовить задание: '+p.stderr[-300:])


def check_task(name, task):
    """All assertions are hard-coded by the training author, and executed in the student's lab."""
    results=[]
    for check in task['checks']:
        proc = exec_script(name, check['script'])
        results.append({'description':check['description'], 'ok':proc.returncode == 0})
    return results


class Terminal:
    def __init__(self, name, distro):
        self.name, self.distro = name, distro
        self.master = None
        self.proc = None

    async def start(self):
        master, slave = pty.openpty()
        self.master = master
        # Interactive shell retains cwd/history, and supports editors and Ctrl+C.
        self.proc = await asyncio.create_subprocess_exec(
            'podman','exec','-it','--workdir=/workspace','--env=TERM=xterm',
            '--env=PS1=\\u@lab:\\w\\$ ',self.name,DISTROS[self.distro]['shell'],
            '--noprofile','--norc','-i',stdin=slave,stdout=slave,stderr=slave,
            start_new_session=True)
        os.close(slave)

    def resize(self, cols, rows):
        if self.master is not None:
            rows = max(12,min(int(rows),70)); cols=max(30,min(int(cols),220))
            fcntl.ioctl(self.master, termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))

    async def write(self, data):
        if self.master is not None:
            await asyncio.to_thread(os.write, self.master, data.encode())

    async def read(self):
        if self.master is None:
            return b''
        try:
            return await asyncio.to_thread(os.read,self.master,4096)
        except OSError:
            return b''

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(),3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self.master is not None:
            os.close(self.master)
            self.master=None
