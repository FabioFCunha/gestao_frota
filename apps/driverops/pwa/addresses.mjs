export function addressLine(input) {
 const cursor=input.selectionStart??input.value.length;
 const start=input.value.lastIndexOf('\n',cursor-1)+1;
 const next=input.value.indexOf('\n',cursor);
 const end=next<0?input.value.length:next;
 return {start,end,text:input.value.slice(start,end).trim()};
}

export function attachAddresses(input,search){
 const selected=new Map();
 const box=document.createElement('div'),status=document.createElement('p'),list=document.createElement('ul');
 box.className='address-suggestions';list.id=input.id+'-suggestions';list.setAttribute('aria-label','Sugestões de endereço');
 status.className='muted';status.setAttribute('role','status');
 input.setAttribute('aria-controls',list.id);input.setAttribute('autocomplete','off');
 box.append(status,list);input.parentElement.after(box);
 let timer=null,controller=null,version=0;
 function dismiss(){clearTimeout(timer);controller?.abort();controller=null;version++;list.replaceChildren();status.textContent='';}
 async function lookup(){
  const line=addressLine(input),ticket=++version;
  if(line.text.length<4||line.text.length>160)return;
  if(!navigator.onLine){status.textContent='Sem conexão. Informe o endereço completo manualmente.';return;}
  controller=new AbortController();
  status.textContent='Buscando endereços…';
  try{
   const data=await search(line.text,controller.signal);
   if(ticket!==version||addressLine(input).text!==line.text)return;
   list.replaceChildren();
   for(const item of data.results??[]){
    const li=document.createElement('li'),button=document.createElement('button');
    button.type='button';button.textContent=item.label;button.className='secondary';
    button.addEventListener('click',()=>{
     if(addressLine(input).text!==line.text){dismiss();return;}
     input.value=input.value.slice(0,line.start)+item.label+input.value.slice(line.end);
     selected.set(item.label,{latitude:item.latitude,longitude:item.longitude});
     dismiss();input.focus();input.setSelectionRange(line.start+item.label.length,line.start+item.label.length);
     status.textContent='Endereço selecionado. Confira o número e o local antes de iniciar.';
    });
    li.append(button);list.append(li);
   }
   status.textContent=list.children.length?'Selecione um endereço abaixo.':'Nenhum endereço encontrado. Acrescente a cidade ou informe o endereço completo.';
  }catch(error){if(ticket===version&&error.name!=='AbortError')status.textContent='Busca indisponível. Você pode informar o endereço completo manualmente.';}
 }
 input.addEventListener('input',()=>{dismiss();timer=setTimeout(lookup,700);});
 input.addEventListener('keydown',event=>{
  if(event.key==='Escape')dismiss();
  if(event.key==='ArrowDown'&&list.firstChild){event.preventDefault();list.querySelector('button').focus();}
 });
 box.addEventListener('keydown',event=>{if(event.key==='Escape'){dismiss();input.focus();}});
 document.addEventListener('click',event=>{if(event.target!==input&&!box.contains(event.target))dismiss();});
 return {points:labels=>labels.map(label=>selected.get(label)??null),clear:()=>{dismiss();selected.clear();}};
}
