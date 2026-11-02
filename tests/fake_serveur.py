"""Serveur de test sans reseau : simule Cominty pour verifier l'interface."""
import json, sys, types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent))
import main
from cominty_sdk import events

PRATIQUES = [
    ("remise-nordavel","Nordavel a toujours 7 % de remise",1,"10 devis sur 60 à 7 %, tous pour Nordavel.","devis.csv"),
    ("fournisseur-aeronyx","Aeronyx passe toujours par Fonderis",4,"7 commandes sur 7 chez Fonderis, à 9,40 €/kg contre 7,80 €/kg.","achats.csv"),
    ("controle-karim-inox","Karim contrôle tout l'inox 316",5,"22 pièces inox 316 sur 22 contrôlées par Karim.","expeditions.csv"),
    ("paiement-breizhydra","Breizhydra paie à 60 jours",2,"10 devis sur 10 à 60 jours.","devis.csv"),
    ("delai-fin-annee","Quatre semaines en fin d'année",3,"10 devis de novembre et décembre à 4 semaines.","devis.csv"),
]
class Run:
    def __init__(s, texte, c): s.t=texte; s.thread=NS(id=uuid4()); s.c=c; s.id=uuid4()
    def __aiter__(s): return s._g()
    async def _g(s):
        b=dict(id="1",correlation_id=1,at="2026-11-02T10:00:00Z")
        yield events.parse_event({**b,"name":"tool_call","status":"running","data":{"name":"read_file","description":"x"}})
        yield events.parse_event({**b,"name":"result","status":"success","data":{"reply":s.t,"cost":{"failed":False,"total":"0.0012"}}})
    async def result(s): return NS(id=s.id,content=s.t)
class Client:
    mem={}; vague=set()
    def __init__(s): s.chat=s; s.memory=NS(list=s.lst,get=s.gt,create=s.creer)
    async def __aenter__(s): return s
    async def __aexit__(s,*a): pass
    async def upload_file(s,*a,**k): return NS(id=str(uuid4()))
    async def creer(s,path,namespace,purpose,content): s.mem[path]=content
    async def lst(s,namespace=None): return [NS(path=p) for p in s.mem]
    async def gt(s,p,namespace=None): return NS(path=p,content=s.mem[p])
    async def start(s,**k):
        if "Camille" in k["message"]: return Run("Faites 7 % tant que Madame Lefort reste acheteuse. Michel Moreau l'a dit.",s)
        return Run("Voici :\n"+json.dumps({"pratiques":[dict(id=a,titre=b,regle=c,preuve=d,sources=[e],question=f"Pourquoi {b.lower()} ?") for a,b,c,d,e in PRATIQUES]}),s)
    async def send(s,t,agent_id,message):
        if "nouvelle version" in message: return Run(json.dumps({"regles":[{"numero":i,"texte":f"Nouvelle regle {i}","changement":f"Exception {i}","source":"Michel Moreau"} for i in range(1,6)]}),s)
        if "dossier" in message: return Run("# Dossier\n\n## Nordavel\nRaison connue.",s)
        pid=message.split('"')[1]
        if "vieil accord" in message: return Run('The answer is vague.\n{"enregistre": false, "relance": "Qui a conclu cet accord ?", "resume": null}',s)
        if "seulement les brides" in message: return Run('{"enregistre": false, "contradiction": true, "relance": "Les entretoises aussi : 11 sur 11 ?", "resume": null}',s)
        s.mem[f"savoir/{pid}.md"]="Raison donnée par Michel Moreau."
        return Run('{"enregistre": true, "relance": null, "resume": "ok"}',s)
    async def export(s,*a,**k): return b"%PDF-1.4 test"
main.make_client=Client
if __name__=="__main__":
    import uvicorn; uvicorn.run(main.app,port=8123,log_level="warning")
