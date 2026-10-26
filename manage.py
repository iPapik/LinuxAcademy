#!/usr/bin/env python3
"""Management CLI; usage: python manage.py create-admin [username]."""
import argparse
import getpass
import sys
from app import storage

p=argparse.ArgumentParser()
p.add_argument('action', choices=['create-admin','reset-password','stats'])
p.add_argument('username',nargs='?',default='admin')
args=p.parse_args()
storage.init_db()
if args.action == 'stats':
    from app.curriculum import stats
    print('Содержимое:',stats(),'Пользователей:',storage.count_users())
else:
    password=getpass.getpass('Пароль (от 12 символов): ')
    again=getpass.getpass('Повторите пароль: ')
    if password!=again:
        sys.exit('Пароли не совпадают')
    try:
        if args.action=='create-admin':
            storage.add_user(args.username,password,admin=True)
            print('Администратор создан:',args.username)
        else:
            with storage.connect() as c:
                row=c.execute('SELECT id FROM users WHERE username=?',(args.username,)).fetchone()
            if not row:
                sys.exit('Не найден пользователь')
            storage.reset_password(row['id'],password)
            print('Пароль обновлён, старые сессии отозваны')
    except ValueError as exc:
        sys.exit(str(exc))
