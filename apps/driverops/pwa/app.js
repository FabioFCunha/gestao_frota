import {attachAddresses} from './addresses.mjs';
import {activeLeg,nextLeg,parseKM,destinations,canSend,googleURL,wazeURL} from './rules.mjs';
const $=id=>document.getElementById(id), API='/api/driver/';
let boot=null,trip=null,busy=false,watch=null,trackingConsent=false,formKey='',lastFix=0,installPrompt=null;
const date=v=>v?new Date(v).toLocaleString('pt-BR'):'—';
async function searchAddresses(query,signal){
 const response=await fetch(API+'addresses/?q='+encodeURIComponent(query),{credentials:'same-origin',cache:'no-store',signal,headers:{Accept:'application/json'}});
 if(!response.ok)throw Error('Busca indisponível');
 return response.json();
}
const addressPickers=Object.fromEntries(['destinations','append'].map(id=>[id,attachAddresses($(id),searchAddresses)]));

function message(text){$('message').textContent=text;}
function lockScreen(){
 stopGPS();trip=null;boot=null;
 Object.values(addressPickers).forEach(p=>p.clear());
 $('identity').textContent='Confirme sua sessão para continuar.';
 for(const id of ['create','trip','transition','extra'])$(id).hidden=true;
 $('history').replaceChildren();$('history-detail').replaceChildren();
}
const database=new Promise((resolve,reject)=>{
 const open=indexedDB.open('transfrota-pwa',1);
 open.onupgradeneeded=()=>open.result.createObjectStore('outbox',{keyPath:'id'});
 open.onsuccess=()=>resolve(open.result);open.onerror=()=>reject(open.error);
});
async function records(){const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction('outbox');const q=tx.objectStore('outbox').getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});}
async function write(record){const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction('outbox','readwrite');tx.objectStore('outbox').put(record);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}
async function remove(id){const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction('outbox','readwrite');tx.objectStore('outbox').delete(id);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}
class ApiError extends Error {constructor(text,status){super(text);this.status=status;}}
function csrf(){return document.cookie.split('; ').find(v=>v.startsWith('csrftoken='))?.split('=').slice(1).join('=')??'';}
async function api(path,body,id,form=false){
 const headers={Accept:'application/json'};
 if(body!==undefined){headers['X-CSRFToken']=decodeURIComponent(csrf());if(!form)headers['Content-Type']='application/json';if(id)headers['Idempotency-Key']=id;}
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
 const response=await fetch(API+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers,
 body:body===undefined?undefined:form?body:JSON.stringify(body),signal:controller.signal});
 let result;
 try{result=await response.json();}catch{throw new ApiError('Resposta inesperada. Verifique sua sessão e a conexão.',response.status);}
 if(!response.ok)throw new ApiError(typeof result.detail==='string'?result.detail:JSON.stringify(result),response.status);
 return result;
 }finally{clearTimeout(timer);}
}
async function pending(){return (await records()).find(r=>r.kind==='command');}
async function sameOwner(){
 const rows=await records();
 if(rows.some(r=>!canSend(r.owner,boot.member_id))){
   lockScreen();
   throw Error('Há dados pendentes de outra conta neste navegador. Saia e entre com o motorista anterior para sincronizar.');
 }
}
async function retry(){
 const row=await pending();if(!row)return;
 await sameOwner();
 try{const result=await api(row.path,row.body,row.id);await remove(row.id);return result;}
 catch(e){if([400,404,409].includes(e.status))await remove(row.id);throw e;}
}
async function command(path,body){
 if(!boot)throw Error('Conecte à internet e confirme sua sessão.');
 await sameOwner();
 if(await pending())throw Error('Sincronize a operação pendente antes de continuar.');
 const row={id:crypto.randomUUID(),owner:boot.member_id,kind:'command',path,body};
 await write(row);return retry();
}
let flushing=false;
async function flush(){
 if(flushing||!boot)return;flushing=true;
 try{
 await sameOwner();
 for(let batch=0;batch<10;batch++){
 const all=(await records()).filter(r=>r.kind==='gps');if(!all.length)break;
 const group=all.filter(r=>r.path===all[0].path).slice(0,200);
 const result=await api(all[0].path,{points:group.map(r=>r.point)});
 for(const id of result.accepted)await remove(id);
 for(const rejected of result.rejected??[]){
 const row=group.find(r=>r.id===rejected.id);
 if(row)await write({...row,kind:'rejected',reason:rejected.reason});
 }
 }
 }finally{flushing=false;}
}
async function counters(){
 const rows=await records(),op=rows.some(r=>r.kind==='command');
 $('pending').hidden=!op;
 $('queue').textContent=rows.filter(r=>r.kind==='gps').length+' posições aguardando envio'+
 (rows.some(r=>r.kind==='rejected')?' · Há posições fora do horário do trecho. Confira data/hora automáticas do celular.':'');
 const disabled=busy||op||!boot;
 for(const id of ['create-form','transition-form','append-form','close-form','photo-form']){
 for(const el of $(id).querySelectorAll('button,input,select,textarea'))el.disabled=disabled;
 }
}
async function run(work,silent=false){
 if(busy)return;busy=true;
 try{await counters();await work();}
 catch(e){
 if(!silent)message(e.name==='AbortError'?'A conexão não respondeu. Use Sincronizar para conferir se a operação foi salva.':e.message);
 if(e.status===401||e.status===403){
   lockScreen();
   $('connection').textContent='Sessão indisponível. Entre novamente para recuperar os dados pendentes.';
   const a=document.createElement('a');a.href='/entrar/?next='+encodeURIComponent('/api/driver/app/');a.textContent='Entrar novamente';$('connection').append(' ',a);
 }
 }finally{busy=false;await counters().catch(()=>{message('Armazenamento local indisponível. Não inicie operações neste navegador.');});}
}
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function showLegs(target,legs){
 target.replaceChildren();
 for(const l of legs){
 const row=el('div',undefined,'leg');
 row.append(el('strong',l.position+'. '+l.destination),el('span',l.ended_at?'Concluído':l.started_at?'Em deslocamento':'Aguardando início','badge'));
 if(l.started_at)row.append(el('p','Saída: '+date(l.started_at)+' · '+l.started_km+' km'));
 if(l.ended_at)row.append(el('p','Chegada: '+date(l.ended_at)+' · '+l.ended_km+' km · '+l.distance_km+' km percorridos · '+Math.round(l.duration_seconds/60)+' min'));
 target.append(row);
 }
}
function orders(){
 const current=$('order').value;
 $('order').replaceChildren(new Option(boot.requires_exit_order?'Selecione a OS':'Sem OS',''));
 $('order').required=!!boot.requires_exit_order;
 $('order-label').textContent=boot.requires_exit_order?'Ordem de saída atribuída a você':'Ordem de saída (opcional)';
 $('os-help').textContent=boot.requires_exit_order&&!boot.exit_orders.length?'Nenhuma OS pendente atribuída a você. Solicite a saída ao gestor ou operador.':'';
 for(const o of boot.exit_orders.filter(o=>String(o.vehicle)===$('vehicle').value))$('order').add(new Option(o.number+' · '+o.destination,o.id));
 if([...$('order').options].some(o=>o.value===current))$('order').value=current;
}
function render(){
 const next=nextLeg(trip),active=activeLeg(trip);
 $('create').hidden=!!trip;$('trip').hidden=!trip;$('extra').hidden=!trip;$('transition').hidden=!next;
 if(!trip){formKey='';stopGPS();return;}
 $('trip-title').textContent='BDT · '+trip.vehicle;
 $('trip-opened').textContent='Motorista: '+trip.driver+' · abertura '+date(trip.opened_at)+' · OS '+(trip.exit_order_number??'Sem OS');
 showLegs($('legs'),trip.legs);
 $('close-form').hidden=!!active;
 if(!next){stopGPS();return;}
 $('transition-title').textContent=active?'Registrar chegada':'Iniciar próximo trecho';
 $('destination').textContent=next.destination;
 $('navigation').hidden=!active;
 $('google').href=googleURL(next.destination,next.destination_latitude,next.destination_longitude);$('waze').href=wazeURL(next.destination,next.destination_latitude,next.destination_longitude);
 $('km-label').textContent=active?'KM final do painel':'Confirme o KM inicial do painel';
 $('transition-submit').textContent=active?'Concluir trecho':'Iniciar trecho';
 $('gps-start').hidden=!active;
 const key=next.id+':'+!!active;
 if(formKey!==key){
 formKey=key;
 const previous=trip.legs.filter(l=>l.ended_at).at(-1);
 const vehicle=boot.vehicles.find(v=>v.label===trip.vehicle);
 $('km').value=String(active?.started_km??previous?.ended_km??vehicle?.suggested_km??'');
 $('notes').value='';$('photo').value='';
 $('checklist').replaceChildren();
 for(const [index,name] of boot.checklist_items.entries()){
 const row=el('fieldset',undefined,'check'),legend=el('legend',name),options=el('div',undefined,'check-options'),noteLabel=el('label','Descreva o problema'),note=el('textarea');
 row.dataset.item=name;
 for(const [text,value] of [['Conforme','ok'],['Problema','problem'],['Não aplicável','na']]){
 const option=el('label',undefined,'check-option'),input=el('input'),caption=el('span',text);
 input.type='radio';input.name='check-'+index;input.value=value;input.required=true;input.className='check-option-input';
 input.addEventListener('change',()=>{noteLabel.hidden=input.value!=='problem';note.required=input.value==='problem';});
 option.append(input,caption);options.append(option);
 }
 note.id='check-note-'+index;noteLabel.htmlFor=note.id;note.maxLength=2000;note.rows=2;noteLabel.hidden=true;noteLabel.append(note);
 row.append(legend,options,noteLabel);$('checklist').append(row);
 }
 }
 if(!active)stopGPS();
 else if(trackingConsent&&!document.hidden)startGPS();
}
async function refresh(){
 const b=await api('bootstrap/');
 if(b.role!=='driver'){location.assign('/api/driver/panel/');return;}
 boot=b;await sameOwner();
 $('identity').textContent=b.name+' · '+b.company;
 $('connection').textContent='Conectado · atualizado '+new Date().toLocaleTimeString('pt-BR');
 trip=b.active_trip;
 const selected=$('vehicle').value;
 $('vehicle').replaceChildren(...b.vehicles.map(v=>new Option(v.label,v.id)));
 if([...$('vehicle').options].some(o=>o.value===selected))$('vehicle').value=selected;
 orders();render();
 const history=await api('trips/');$('history').replaceChildren();
 for(const t of history.filter(t=>t.closed_at)){
 const button=el('button',t.vehicle+' · '+date(t.opened_at),'secondary');button.type='button';
 button.addEventListener('click',()=>{const target=$('history-detail');target.replaceChildren(el('h3','Encerrado em '+date(t.closed_at)));const rows=el('div');showLegs(rows,t.legs);target.append(rows);});
 $('history').append(button);
 }
 await counters();
}
function stopGPS(){
 if(watch!==null)navigator.geolocation.clearWatch(watch);
 watch=null;$('gps').textContent='GPS parado · a PWA não acompanha a viagem com a página oculta.';
}
function startGPS(){
 const leg=activeLeg(trip);
 if(!leg||document.hidden||watch!==null||!boot)return;
 if(!navigator.geolocation){$('gps').textContent='Localização indisponível neste navegador.';return;}
 const owner=boot.member_id,tripId=trip.id,legId=leg.id;
 $('gps').textContent='Aguardando posição do GPS…';
 watch=navigator.geolocation.watchPosition(async pos=>{
 if(document.hidden||!activeLeg(trip)||activeLeg(trip).id!==legId)return;
 if(pos.timestamp< Date.parse(leg.started_at)||pos.timestamp-lastFix<10000)return;
 lastFix=pos.timestamp;
 const id=crypto.randomUUID(),point={id,latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy:pos.coords.accuracy,measured_at:new Date(pos.timestamp).toISOString()};
 try{
 await write({id,kind:'gps',owner,path:'trips/'+tripId+'/legs/'+legId+'/locations/',point});
 $('gps').textContent='Última posição '+new Date(pos.timestamp).toLocaleTimeString('pt-BR')+' · precisão '+Math.round(pos.coords.accuracy)+' m';
 await flush();await counters();
 }catch{$('gps').textContent='Posição pendente de sincronização. Confira a conexão.';}
 },error=>{$('gps').textContent='GPS indisponível: '+error.message;},{enableHighAccuracy:true,maximumAge:0,timeout:20000});
}
$('vehicle').addEventListener('change',orders);
$('order').addEventListener('change',()=>{
 const order=boot?.exit_orders.find(o=>o.id===$('order').value);
 if(order&&!$('destinations').value.trim())$('destinations').value=order.destination;
});
$('create-form').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
 const labels=destinations($('destinations').value);
 const body={vehicle:Number($('vehicle').value),destinations:labels,destination_points:addressPickers.destinations.points(labels)};
 if(boot.requires_exit_order&&!$('order').value)throw Error('Selecione a OS atribuída a você.');
 if($('order').value)body.exit_order=$('order').value;
 await command('trips/',body);$('destinations').value='';addressPickers.destinations.clear();await refresh();message('BDT aberto. Confira a vistoria e inicie o primeiro trecho.');
});});
$('transition-form').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
 const leg=nextLeg(trip),active=activeLeg(trip);if(!leg)throw Error('Nenhum trecho pendente.');
 const checklist={};
 for(const row of $('checklist').children){const selected=row.querySelector('input[type="radio"]:checked'),note=row.querySelector('textarea');
 if(!selected)throw Error('Confira todos os itens da vistoria.');
 if(selected.value==='problem'&&!note.value.trim())throw Error('Descreva cada problema.');
 checklist[row.dataset.item]={status:selected.value,note:selected.value==='problem'?note.value:''};
 }
 const result=await command('trips/'+trip.id+'/'+(active?'finish':'start')+'/',{leg:leg.id,km:parseKM($('km').value),checklist,notes:$('notes').value});
 if(active)stopGPS();
 else trackingConsent=true;
 trip=result.closed_at?null:result;render();
 await refresh();
 message(active?(result.closed_at?'BDT encerrado com sucesso.':'Chegada salva. Inicie o próximo trecho quando estiver pronto.'):'Trecho iniciado. Volte à PWA para registrar a chegada.');
});});
$('append-form').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
 const labels=destinations($('append').value);
 await command('trips/'+trip.id+'/append/',{destinations:labels,destination_points:addressPickers.append.points(labels)});$('append').value='';addressPickers.append.clear();await refresh();message('Destinos adicionados.');
});});
$('close-form').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
 if(!confirm('Encerrar o BDT sem realizar os destinos restantes?'))return;
 await command('trips/'+trip.id+'/close/',{reason:$('reason').value});stopGPS();$('reason').value='';await refresh();message('BDT encerrado com justificativa.');
});});
$('photo-form').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
 const file=$('photo').files[0],leg=nextLeg(trip);if(!file||!leg)throw Error('Escolha uma imagem para a vistoria.');
 if(file.size>5*1024*1024)throw Error('Use uma foto com até 5 MB.');
 const data=new FormData();data.append('image',file);data.append('moment',activeLeg(trip)?'arrival':'departure');
 await api('trips/'+trip.id+'/legs/'+leg.id+'/photos/',data,undefined,true);
 $('photo').value='';message('Foto da vistoria salva.');
});});
$('gps-start').addEventListener('click',()=>{trackingConsent=true;stopGPS();startGPS();});
$('sync').addEventListener('click',()=>void run(async()=>{if(!boot)await refresh();await retry();await flush();await refresh();message('Sincronização concluída.');}));
$('reload').addEventListener('click',()=>void run(refresh));
$('signout').addEventListener('click',()=>void run(async()=>{
 const rows=await records();
 if(boot&&rows.some(r=>r.kind!=='rejected'&&canSend(r.owner,boot.member_id)))throw Error('Sincronize os dados antes de sair.');
 await api('app/signout/',{});stopGPS();
 // The SW caches only the anonymous shell; remove it on explicit signout too.
 for(const key of await caches.keys())if(key.startsWith('transfrota-pwa-'))await caches.delete(key);
 location.assign('/entrar/?next='+encodeURIComponent('/api/driver/app/'));
}));
window.addEventListener('online',()=>void run(async()=>{await refresh();await retry();await flush();await refresh();},true));
window.addEventListener('offline',()=>{$('connection').textContent='Sem conexão. Operações exigem confirmação do servidor. Posições já coletadas permanecem na fila.';});
document.addEventListener('visibilitychange',()=>{
 if(document.hidden)stopGPS();
 else void run(async()=>{await refresh();if(trackingConsent)startGPS();await flush();},true);
});
window.addEventListener('pagehide',stopGPS);
setInterval(()=>{if(!document.hidden&&boot&&navigator.onLine)void run(async()=>{await flush();await refresh();},true);},30000);
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('install').hidden=false;});
$('install').addEventListener('click',async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('install').hidden=true;}});
if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js',{scope:'./'}).catch(()=>message('A instalação não está disponível neste navegador. Você pode testar pela página.'));
void run(refresh);
