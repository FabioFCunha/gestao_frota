import test from 'node:test';
import assert from 'node:assert/strict';
import {activeLeg,nextLeg,parseKM,destinations,canSend,googleURL,wazeURL} from './rules.mjs';

test('chegada avança ao próximo destino sem iniciá-lo automaticamente',()=>{
 const trip={legs:[{id:'a',started_at:'2026-10-20',ended_at:'2026-10-20'},{id:'b',started_at:null,ended_at:null}]};
 assert.equal(activeLeg(trip),null);
 assert.equal(nextLeg(trip).id,'b');
});
test('KM inteiro e endereços são validados antes da fila',()=>{
 assert.equal(parseKM('0'),0);assert.equal(parseKM('125400'),125400);
 for(const value of ['','-1','1.2','10abc','10000000'])assert.throws(()=>parseKM(value));
 assert.deepEqual(destinations(' Rua A \n\n Base '),['Rua A','Base']);
 assert.throws(()=>destinations(' '));
 assert.throws(()=>destinations('a'.repeat(301)));
});
test('fila não pode ser enviada por outro motorista',()=>{
 assert.equal(canSend(1,'1'),true);assert.equal(canSend(1,2),false);
});
test('destino é codificado no link de navegação',()=>{
 const url=new URL(googleURL('Rua A & Rua B, 12'));
 assert.equal(url.searchParams.get('destination'),'Rua A & Rua B, 12');
 assert.equal(url.searchParams.get('api'),'1');
});

test('navegação usa coordenadas escolhidas e preserva endereços manuais',()=>{
 assert.equal(new URL(googleURL('Praça XV',-22.9,-43.17)).searchParams.get('destination'),'-22.9,-43.17');
 assert.equal(new URL(wazeURL('Origem',0,0)).searchParams.get('ll'),'0,0');
 assert.equal(new URL(wazeURL('Rua A',null,null)).searchParams.get('q'),'Rua A');
});
