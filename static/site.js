'use strict';
const csrf = document.querySelector('meta[name="csrf"]')?.content || '';
let toastTimeout;
function toast(message, error=false){
  const el=document.getElementById('toast');
  if(!el)return;
  el.textContent=String(message);el.classList.toggle('error',error);el.classList.add('show');
  clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>el.classList.remove('show'),4800);
}
async function api(url,data={}){
 const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});
 const obj=await response.json().catch(()=>({error:'Неполный ответ сервера'}));
 if(!response.ok || !obj.ok)throw new Error(obj.error || obj.detail || `Ошибка ${response.status}`);
 return obj;
}
const menu=document.getElementById('menuToggle');
if(menu)menu.onclick=()=>document.getElementById('sidebar')?.classList.toggle('open');
const logout=document.getElementById('logoutBtn');
if(logout)logout.onclick=async()=>{try{await api('/logout');location.href='/login';}catch(err){toast(err.message,true)}};
const markRead=document.getElementById('markRead');
if(markRead)markRead.onclick=async()=>{
  markRead.disabled=true;
  try{
    await api('/api/lesson/'+markRead.dataset.lesson+'/read');
    document.getElementById('readCta').hidden=true;
    const quiz=document.getElementById('quiz');
    if(quiz){quiz.hidden=false;quiz.scrollIntoView({behavior:'smooth',block:'start'});}
    document.getElementById('stepRead')?.classList.add('complete');
    document.getElementById('stepQuiz')?.classList.add('current');
    toast('Теория пройдена. Теперь проверьте знания.');
  }catch(err){toast(err.message,true);markRead.disabled=false;}
};

const search=document.getElementById('courseSearch');
if(search)search.oninput=()=>{const query=search.value.trim().toLowerCase();document.querySelectorAll('.module-card').forEach(card=>card.hidden=!card.dataset.search.includes(query))};

function unlockNextLesson(){
 const locked=document.getElementById('nextLessonLocked');
 if(!locked)return;
 const id=locked.dataset.nextLesson;
 if(!/^m[0-9]{2}-l[0-9]{2}$/.test(id))return;
 const link=document.createElement('a');
 link.href='/lesson/'+id;
 link.className='btn secondary';
 link.textContent='Следующий урок →';
 locked.replaceWith(link);
 document.getElementById('stepPractice')?.classList.add('complete');
 toast('Урок завершён. Следующий урок открыт!');
}
for(const button of document.querySelectorAll('[data-prepare]')){
 button.onclick=async()=>{
  button.disabled=true;
  try{const result=await api(`/api/task/${button.dataset.prepare}/prepare`);toast('Файлы задания подготовлены. Откройте терминал '+result.distro+'.');}
  catch(err){toast(err.message,true)}finally{button.disabled=false}
 };
}
for(const button of document.querySelectorAll('[data-verify]')){
 button.onclick=async()=>{
  button.disabled=true;
  try{
   const id=button.dataset.verify;
   const result=await api(`/api/task/${id}/verify`);
   const target=document.getElementById(`result-${id}`);target.replaceChildren();
   for(const test of result.checks){const p=document.createElement('div');p.className='check-result '+(test.ok?'pass':'fail');p.textContent=test.description;target.appendChild(p)}
   if(result.passed){const badge=document.querySelector(`[data-task-status="${id}"]`);badge.className='status-chip done';badge.textContent='✓ Пройдено';toast('Отлично. Все проверки пройдены!');if(result.lesson_completed)unlockNextLesson()}
   else toast('Не все критерии выполнены. Посмотрите результаты проверки.',true);
  }catch(err){toast(err.message,true)}finally{button.disabled=false}
 };
}
const submitQuiz=document.getElementById('submitQuiz');
if(submitQuiz){
 submitQuiz.onclick=async()=>{
  const answers={};const questions=document.querySelectorAll('.question');
  for(const question of questions){const checked=question.querySelector('input:checked');if(!checked){toast('Сначала ответьте на все вопросы.',true);question.scrollIntoView({behavior:'smooth',block:'center'});return}answers[checked.name]=checked.value}
  submitQuiz.disabled=true;
  try{const res=await api('/api/quiz/'+submitQuiz.dataset.lesson,{answers});
    for(const item of res.checks){const feedback=document.querySelector(`[data-q-feedback="${item.id}"]`);feedback.className='q-feedback '+(item.passed?'':'fail');feedback.textContent=(item.passed?'✓ Правильно. ':'× Неверно. ')+item.explanation}
    const result=document.getElementById('quizResult');result.className='quiz-result '+(res.passed?'':'fail');result.textContent=`Результат: ${res.score} из ${res.total}. ${res.passed?'Тест сдан.':'Для зачёта необходимо набрать не менее 70%. Можно повторить.'}`;
    if(res.passed){
      if(res.lesson_completed)unlockNextLesson();
      const labs=document.getElementById('tasks');
      if(labs){labs.hidden=false;document.getElementById('stepQuiz')?.classList.add('complete');document.getElementById('stepPractice')?.classList.add('current');}
      if(labs)labs.scrollIntoView({behavior:'smooth',block:'start'});
    }
    toast(res.passed?'Тест пройден!':'Тест не сдан. Повторите материал.',!res.passed);
  }catch(err){toast(err.message,true)}finally{submitQuiz.disabled=false}
 };
}
const createForm=document.getElementById('createUserForm');
if(createForm)createForm.onsubmit=async(ev)=>{
 ev.preventDefault();const form=new FormData(createForm);
 try{await api('/api/admin/users',{username:form.get('username'),password:form.get('password')});toast('Пользователь создан');setTimeout(()=>location.reload(),650)}catch(err){toast(err.message,true)}
};
for(const button of document.querySelectorAll('[data-reset-password]')){
 button.onclick=async()=>{
  const password=prompt(`Новый пароль для ${button.dataset.username} (не менее 12 символов):`);
  if(password===null)return;
  try{await api(`/api/admin/users/${button.dataset.resetPassword}/password`,{username:button.dataset.username,password});toast('Пароль изменён. Предыдущие сессии завершены.')}catch(err){toast(err.message,true)}
 };
}
