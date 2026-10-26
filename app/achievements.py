"""Server-verified achievements, awarded once and persisted in SQLite."""
from . import storage
from .curriculum import MODULES, LESSONS, TASKS

BADGES = [
    ('first_read','📖','Первое знакомство','Прочитать первую тему и отметить её изученной.'),
    ('first_quiz','🧠','Теория усвоена','Успешно сдать первый тест.'),
    ('first_task','⌨','Первый терминал','Выполнить первое проверяемое задание.'),
    ('first_lesson','🌱','Первый шаг','Полностью завершить первый урок.'),
    ('first_chapter','🏁','Первая глава','Полностью закончить учебный раздел.'),
    ('five_lessons','⭐','Пять уроков','Полностью завершить пять уроков.'),
    ('ten_lessons','🏅','Постоянство','Полностью завершить десять уроков.'),
    ('twentyfive_lessons','🏆','Системный инженер','Полностью завершить 25 уроков.'),
    ('ten_quizzes','🎯','Эрудит','Сдать десять контрольных тестов.'),
    ('ten_tasks','🛠','Практик','Успешно выполнить десять заданий.'),
    ('three_families','🌍','Три семейства','Выполнить задания в Ubuntu, Debian и AlmaLinux.'),
    ('three_chapters','🚀','Курс на эксперта','Полностью пройти три учебных раздела.'),
    ('all_lessons','👑','Мастер Linux','Завершить все уроки учебной программы.'),
    ('registered','🔒','Сохраняю прогресс','Зарегистрировать постоянную учётную запись.')
]


def snapshot(user):
    done=storage.completed(user['id'])
    reads={item for kind,item in done if kind=='read'}
    quizzes={item for kind,item in done if kind=='quiz'}
    tasks={item for kind,item in done if kind=='task'}
    lessons={item for kind,item in done if kind=='lesson'}
    completed_modules=[
        m for m in MODULES if m['lessons'] and all(l['id'] in lessons for l in m['lessons'])
    ]
    families={TASKS[t]['distro'] for t in tasks if t in TASKS}
    eligibility={
        'first_read':bool(reads or lessons),
        'first_quiz':bool(quizzes),
        'first_task':bool(tasks),
        'first_lesson':bool(lessons),
        'first_chapter':bool(completed_modules),
        'five_lessons':len(lessons)>=5,
        'ten_lessons':len(lessons)>=10,
        'twentyfive_lessons':len(lessons)>=25,
        'ten_quizzes':len(quizzes)>=10,
        'ten_tasks':len(tasks)>=10,
        'three_families':{'ubuntu','debian','alma'}.issubset(families),
        'three_chapters':len(completed_modules)>=3,
        'all_lessons':len(lessons)>=len(LESSONS),
        'registered':not bool(user.get('is_guest',True)),
    }
    storage.award_badges(user['id'],[key for key,on in eligibility.items() if on])
    awarded=storage.awarded_badges(user['id'])
    badges=[
        {'id':key,'icon':icon,'title':title,'description':description,
         'earned':key in awarded,'earned_at':awarded.get(key)}
        for key,icon,title,description in BADGES
    ]
    xp=len(reads)*5+len(quizzes)*20+len(tasks)*30+len(lessons)*50
    return {'badges':badges,'earned':sum(b['earned'] for b in badges),
            'total':len(badges),'xp':xp,'level':xp//300+1,
            'lessons':len(lessons),'quizzes':len(quizzes),
            'tasks':len(tasks),'chapters':len(completed_modules),
            'total_lessons':len(LESSONS)}
