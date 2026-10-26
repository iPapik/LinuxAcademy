'use strict';
const shell=document.getElementById('terminalShell');
const distro=shell.dataset.distro;
const target=document.getElementById('terminal');
const statusEl=document.getElementById('labStatus');
let socket=null,term=null;
let reconnecting=false;
function status(text){statusEl.textContent=text}
function dimensions(){
 const containerWidth=target.clientWidth-32,containerHeight=target.clientHeight-22;
 return {cols:Math.max(40,Math.min(180,Math.floor(containerWidth/9.0))),rows:Math.max(18,Math.min(60,Math.floor(containerHeight/17.0)))};
}
async function connectTerminal(){
 if(reconnecting)return;
 reconnecting=true;
 try{
  if(socket){socket.close();socket=null}
  if(term){term.destroy();term=null}
  status('● Подготовка окружения…');
  await api('/api/lab/start',{distro});
  if(typeof Terminal==='undefined')throw new Error('Не загружен локальный терминал xterm.js');
  target.replaceChildren();
  const d=dimensions();
  term=new Terminal({cols:d.cols,rows:d.rows,cursorBlink:true,convertEol:false,scrollback:1500,
    fontFamily:'Consolas,Monaco,monospace',fontSize:14,theme:{background:'#061219',foreground:'#d6e9ed',cursor:'#64ddbe'}});
  term.open(target);term.focus();
  const scheme=location.protocol==='https:'?'wss':'ws';
  socket=new WebSocket(`${scheme}://${location.host}/ws/${distro}`);socket.binaryType='arraybuffer';
  socket.onopen=()=>{status('● Подключено · '+distro);socket.send(JSON.stringify({type:'resize',cols:d.cols,rows:d.rows}));term.focus()};
  socket.onmessage=event=>{
   if(typeof event.data==='string'){
    try{const obj=JSON.parse(event.data);if(obj.type==='error'){term.write('\r\n'+obj.message+'\r\n');toast(obj.message,true)}else term.write(event.data)}catch{term.write(event.data)}
   }else term.write(new TextDecoder().decode(event.data));
  };
  socket.onclose=()=>{status('○ Терминал отключён');if(term)term.write('\r\n[Сессия завершена. Нажмите «Подключиться» для новой сессии.]\r\n')};
  socket.onerror=()=>status('× Ошибка соединения WebSocket');
  term.on('data',data=>{if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'input',data}))});
 }catch(err){status('× '+err.message);toast(err.message,true)}finally{reconnecting=false}
}
const reconnect=document.getElementById('reconnect');
reconnect.onclick=()=>connectTerminal();
document.getElementById('resetLab').onclick=async()=>{
 if(!confirm('Удалить ВСЕ данные текущей лаборатории '+distro+'? Действие необратимо.'))return;
 try{
  socket?.close();
  // Give the WebSocket session time to close; reset refuses active terminals.
  await new Promise(resolve=>{if(!socket||socket.readyState===WebSocket.CLOSED){resolve();return}socket.addEventListener('close',resolve,{once:true});setTimeout(resolve,2200)});
  const response=await api('/api/lab/reset',{distro});toast('Окружение очищено');await connectTerminal();
 }catch(err){toast(err.message,true)}
};
window.addEventListener('resize',()=>{if(!term||!socket||socket.readyState!==WebSocket.OPEN)return;const d=dimensions();term.resize(d.cols,d.rows);socket.send(JSON.stringify({type:'resize',...d}))});
window.addEventListener('beforeunload',()=>socket?.close());
connectTerminal();
