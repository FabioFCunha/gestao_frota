import React, { useEffect, useState } from 'react';
import { Alert, AppState, Button, Linking, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import * as ImagePicker from 'expo-image-picker';
import { api, ApiError, photo, saveToken, token, forgetToken } from './src/api';
import { command, flush, gpsStatus, pendingCommand, prepareGPS, retryCommand, startGPS, stopGPS } from './src/tracking';
import type { Bootstrap, Checklist, Leg, Trip } from './src/types';

function Screen() {
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false);
  const [user, setUser] = useState(''), [password, setPassword] = useState('');
  const [boot, setBoot] = useState<Bootstrap|null>(null), [trip, setTrip] = useState<Trip|null>(null);
  const [history, setHistory] = useState<Trip[]>([]), [vehicle, setVehicle] = useState<number|null>(null);
  const [dest, setDest] = useState(''), [os, setOS] = useState(''), [append, setAppend] = useState('');
  const [odometer, setOdometer] = useState(''), [checks, setChecks] = useState<Checklist>({});
  const [notes, setNotes] = useState(''), [reason, setReason] = useState('');
  const [pending, setPending] = useState(false), [status, setStatus] = useState('GPS parado');
  const [selected, setSelected] = useState<Trip|null>(null);
  const active = trip?.legs.find(l => l.started_at && !l.ended_at);
  const next = trip?.legs.find(l => !l.ended_at);

  async function refresh() {
    const b: Bootstrap = await api('bootstrap/');
    setBoot(b); setTrip(b.active_trip); setVehicle(v=>v ?? b.vehicles[0]?.id ?? null);
    setHistory(await api('trips/'));
    setReady(true);
    const p = await pendingCommand();
    setPending(!!p);
    const a = b.active_trip?.legs.find(l=>l.started_at && !l.ended_at);
    if (!a) await stopGPS();
    // Existing native task continues; restart only after permissions were granted.
    else {
      try { await startGPS(b.active_trip!.id, a.id, a.started_at!); }
      catch { setStatus('Trecho ativo sem GPS: toque em Retomar GPS.'); }
    }
    await updateStatus();
  }
  async function updateStatus() {
    const s = await gpsStatus();
    setStatus((s.active ? 'GPS em deslocamento' : 'GPS parado')+' · '+s.pending+' posições pendentes'+(s.rejected ? ' · '+s.rejected+' posições fora do intervalo; confira data/hora do celular' : '')+(s.error?' · '+s.error:''));
    setPending(!!await pendingCommand());
  }
  async function run(work:()=>Promise<void>) {
    if (busy) return;
    setBusy(true);
    try { await work(); }
    catch (e) {
      Alert.alert('Atenção', e instanceof Error ? e.message : 'Não foi possível concluir.');
      if (e instanceof ApiError && e.status === 401) { setReady(false); setBoot(null); }
    } finally { setBusy(false); await updateStatus().catch(()=>{}); }
  }
  useEffect(()=>{
    void run(async()=>{if(await token()) await refresh();});
    const sub = AppState.addEventListener('change', state=> {
      if(state==='active') void run(async()=>{ if(await token()) {await flush(); await refresh();} });
    });
    return ()=>sub.remove();
  },[]);
  useEffect(()=>{
    if (!next) return;
    const previous = trip?.legs.filter(l=>l.ended_at).slice(-1)[0];
    const suggested = active?.started_km ?? previous?.ended_km ?? boot?.vehicles.find(v=>v.id===vehicle)?.suggested_km;
    setOdometer(suggested == null ? '' : String(suggested));
    setChecks(Object.fromEntries((boot?.checklist_items??[]).map(k=>[k,{status:'',note:''}])));
    setNotes('');
  },[next?.id, active?.id, vehicle, boot?.checklist_items.join(',')]);

  async function signIn() {
    const result = await api('login/',{username:user,password});
    const previous = await SecureStore.getItemAsync('driver-owner');
    const state = await gpsStatus();
    if (previous && previous!==String(result.member_id) && (state.pending || await pendingCommand())) {
      throw new Error('Há dados pendentes de outro motorista. Entre com a conta anterior e sincronize antes de trocar.');
    }
    await saveToken(result.token);
    await SecureStore.setItemAsync('driver-owner', String(result.member_id));
    setPassword(''); await refresh();
  }
  async function transition(action:'start'|'finish') {
    if (!trip || !next) return;
    if (!/^\d+$/.test(odometer)) throw new Error('Informe o KM inteiro.');
    if (action==='start') await prepareGPS();
    const result:Trip = await command('trips/'+trip.id+'/'+action+'/', {
      leg:next.id,km:Number(odometer),checklist:checks,notes,
    });
    setTrip(result.closed_at ? null : result);
    if (action==='start') {
      const leg = result.legs.find(l=>l.id===next.id)!;
      try { await startGPS(result.id, leg.id, leg.started_at!); }
      catch { Alert.alert('GPS', 'O trecho foi iniciado, mas o GPS não ativou. Toque em Retomar GPS.'); }
    } else {
      await stopGPS();
      try {await flush();} catch { /* GPS remains queued */ }
    }
    await refresh();
  }
  async function takePhoto(leg:Leg, moment:string) {
    if (!trip) return;
    if (!(await ImagePicker.requestCameraPermissionsAsync()).granted) throw new Error('Permita o uso da câmera.');
    const result = await ImagePicker.launchCameraAsync({mediaTypes:['images'],quality:0.65,exif:false});
    if(result.canceled) return;
    await photo('trips/'+trip.id+'/legs/'+leg.id+'/photos/',result.assets[0].uri,moment);
    Alert.alert('Vistoria', 'Foto salva.');
  }
  const btn=(title:string,work:()=>Promise<void>,disabled=false)=><View style={s.button}><Button title={title} disabled={busy||disabled} onPress={()=>void run(work)}/></View>;
  const field=(label:string,value:string,set:(v:string)=>void,numeric=false,multi=false)=><View style={s.field}><Text style={s.label}>{label}</Text><TextInput style={s.input} value={value} onChangeText={set} editable={!busy} keyboardType={numeric?'number-pad':'default'} multiline={multi} autoCapitalize="none"/></View>;
  return <SafeAreaView style={s.safe}><ScrollView contentContainerStyle={s.page} keyboardShouldPersistTaps="handled">
    <Text style={s.brand}>TRANSFROTA</Text><Text style={s.title}>Motorista</Text>
    {!ready ? <>
      <Text style={s.muted}>Entre com o usuário cadastrado pela empresa.</Text>
      {field('Usuário',user,setUser)}
      <Text style={s.label}>Senha</Text><TextInput style={s.input} value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" editable={!busy}/>
      {btn('Entrar',signIn)}
    </> : <>
      <Text>{boot?.name} · {boot?.company}</Text>
      <View style={s.card}><Text>{status}</Text>{pending && <Text style={s.warning}>Operação aguardando confirmação. Sincronize antes de continuar.</Text>}
      {btn('Sincronizar',async()=>{await retryCommand(); await flush(); await refresh();})}</View>
      {boot?.role!=='driver' ? <Text>Use o painel do gestor para acompanhar os BDTs da empresa.</Text> : !trip ? <View style={s.card}>
        <Text style={s.h2}>Abrir BDT</Text><Text style={s.muted}>Escolha o veículo e informe os destinos na ordem da viagem.</Text>
        {boot.vehicles.map(v=><View key={v.id}>{btn((v.id===vehicle?'✓ ':'')+v.label,async()=>{setVehicle(v.id);})}</View>)}
        {field('Destinos: um endereço completo por linha',dest,setDest,false,true)}
        {field('ID da OS (opcional)',os,setOS)}
        {btn('Abrir BDT',async()=>{
          const result:Trip = await command('trips/',{vehicle,destinations:dest.split('\n').map(v=>v.trim()).filter(Boolean),...(os?{exit_order:os}:{})});
          setTrip(result); setDest(''); setOS(''); await refresh();
        },pending||!vehicle)}
      </View> : <>
        <View style={s.card}><Text style={s.h2}>BDT · {trip.vehicle}</Text><Text>{trip.id.slice(0,8)} · aberto {new Date(trip.opened_at).toLocaleString('pt-BR')}</Text>
          {trip.legs.map(l=><View key={l.id} style={s.leg}>
            <Text style={s.label}>{l.position}. {l.destination}</Text>
            <Text>{l.ended_at?'Concluído':l.started_at?'Em deslocamento':'Aguardando início'}</Text>
            {l.started_at && <Text>Saída: {new Date(l.started_at).toLocaleString('pt-BR')} · {l.started_km} km</Text>}
            {l.ended_at && <Text>Chegada: {new Date(l.ended_at).toLocaleString('pt-BR')} · {l.ended_km} km · {l.distance_km} km percorridos · {Math.round((l.duration_seconds??0)/60)} min</Text>}
          </View>)}
        </View>
        {next && <View style={s.card}><Text style={s.h2}>{active?'Chegada ao destino':'Próximo trecho'}</Text><Text>{next.destination}</Text>
          {active && <>
            {btn('Navegar no Google Maps',async()=>{await Linking.openURL('https://www.google.com/maps/dir/?api=1&travelmode=driving&dir_action=navigate&destination='+encodeURIComponent(next.destination));})}
            {btn('Navegar no Waze',async()=>{await Linking.openURL('https://waze.com/ul?q='+encodeURIComponent(next.destination)+'&navigate=yes');})}
            {btn('Retomar GPS',async()=>{await prepareGPS(); await startGPS(trip.id,next.id,next.started_at!);})}
          </>}
          {field(active?'KM final do painel':'Confirme o KM inicial do painel',odometer,setOdometer,true)}
          <Text style={s.h2}>Vistoria {active?'de chegada':'de saída'}</Text>
          <Text style={s.muted}>Confira cada item. N/A significa não aplicável.</Text>
          {Object.entries(checks).map(([key,value])=><View key={key} style={s.leg}>
            <Text style={s.label}>{key}</Text>
            <View style={s.row}>{(['ok','problem','na'] as const).map(st=><View style={s.choice} key={st}><Button disabled={busy} title={(value.status===st?'✓ ':'')+({ok:'Conforme',problem:'Problema',na:'N/A'}[st])} onPress={()=>setChecks({...checks,[key]:{...value,status:st}})}/></View>)}</View>
            {value.status==='problem' && field('Descreva o problema',value.note,n=>setChecks({...checks,[key]:{...value,note:n}}),false,true)}
          </View>)}
          {btn('Fotografar vistoria',async()=>takePhoto(next,active?'arrival':'departure'),pending)}
          {active && field('Observações da chegada',notes,setNotes,false,true)}
          {btn(active?'Concluir trecho com KM final':'Iniciar trecho',async()=>transition(active?'finish':'start'),pending)}
          <Text style={s.muted}>Ao concluir o último destino, o BDT será encerrado. Cadastre o retorno antes disso se ele fizer parte desta viagem.</Text>
        </View>}
        <View style={s.card}><Text style={s.h2}>Adicionar destinos ou retorno</Text>
          {field('Endereços completos: um por linha',append,setAppend,false,true)}
          {btn('Adicionar à viagem',async()=>{await command('trips/'+trip.id+'/append/',{destinations:append.split('\n').map(v=>v.trim()).filter(Boolean)});setAppend('');await refresh();},pending)}
          {!active && <>
            {field('Motivo para encerrar antes do último destino',reason,setReason,false,true)}
            {btn('Encerrar BDT antecipadamente',async()=>{await command('trips/'+trip.id+'/close/',{reason});setReason('');await refresh();},pending)}
          </>}
        </View>
      </>}
      <Text style={s.h2}>Histórico de BDTs</Text>
      {history.filter(t=>t.closed_at).map(t=><View key={t.id}>{btn(t.vehicle+' · '+new Date(t.opened_at).toLocaleDateString('pt-BR'),async()=>{setSelected(t);})}</View>)}
      {selected && <View style={s.card}><Text style={s.h2}>{selected.vehicle}</Text>{selected.legs.map(l=><View style={s.leg} key={l.id}><Text>{l.destination}</Text><Text>{l.started_km??'—'} → {l.ended_km??'—'} km · {l.distance_km??'—'} km percorridos</Text><Text>{l.started_at?new Date(l.started_at).toLocaleString('pt-BR'):'Não iniciado'} / {l.ended_at?new Date(l.ended_at).toLocaleString('pt-BR'):'Não concluído'}</Text></View>)}</View>}
      {btn('Sair',async()=>{
        const state=await gpsStatus();
        if(trip||state.pending||await pendingCommand()) throw new Error('Encerre o BDT e sincronize os dados antes de sair.');
        await api('logout/',{}); await forgetToken(); setBoot(null);setReady(false);setHistory([]);
      })}
    </>}
    <Text style={s.footer}>Versão de homologação · confira o KM no painel do veículo</Text>
  </ScrollView></SafeAreaView>;
}
export default function App(){return <SafeAreaProvider><Screen/></SafeAreaProvider>;}
const s=StyleSheet.create({
 safe:{flex:1,backgroundColor:'#f1f5f9'},page:{padding:20,paddingBottom:50},brand:{fontWeight:'800',color:'#0f766e',letterSpacing:3,fontSize:15},
 title:{fontSize:30,fontWeight:'700',color:'#0f172a',marginBottom:14},h2:{fontSize:20,fontWeight:'700',marginVertical:10,color:'#0f172a'},
 card:{backgroundColor:'white',padding:18,borderRadius:16,marginTop:16},field:{marginVertical:9},input:{borderWidth:1,borderColor:'#94a3b8',borderRadius:8,padding:12,backgroundColor:'#fff',fontSize:16,minHeight:48},
 label:{fontWeight:'600',fontSize:15,marginBottom:5},muted:{color:'#475569',lineHeight:21},button:{marginVertical:6},leg:{paddingVertical:12,borderBottomWidth:1,borderColor:'#e2e8f0'},
 row:{flexDirection:'row',flexWrap:'wrap',gap:6},choice:{flexGrow:1},warning:{color:'#92400e',marginVertical:8},footer:{color:'#64748b',marginTop:28,textAlign:'center'},
});
