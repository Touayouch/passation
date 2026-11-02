"""Passation : l'agent qui interroge un employe avant son depart.

Tous les comportements d'agent passent par Cominty :
fichiers, conversations, memoire partagee, export PDF et suivi des couts.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator

from cominty_sdk import (
    AgentCapabilities,
    AsyncCominty,
    ComintyError,
    MemoryCapability,
    events,
)
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ICI = Path(__file__).parent
DOCS = ICI / "docs_demo"
AGENT_ID = os.getenv("COMINTY_AGENT_ID", "syhRMkNYmsmZ")
MAX_SESSIONS = 50
TYPES = {".csv": "text/csv", ".txt": "text/plain"}

PROMPT_ENQUETE = """Michel Moreau, responsable commercial, quitte l'entreprise.
Analyse les 5 fichiers joints et trouve les 5 pratiques les plus importantes qui ne sont
pas ecrites ou qui contredisent les procedures. Calcule les faits sur les donnees.
Ne devine jamais une raison.

Reponds uniquement avec ce JSON, sans texte autour :
{"pratiques": [{
  "id": "identifiant-court-en-minuscules",
  "titre": "la pratique en une phrase courte",
  "regle": numero de la regle officielle contredite (1 a 5) ou null,
  "preuve": "les faits exacts, avec chiffres",
  "sources": ["fichier.csv"],
  "question": "une seule question courte pour Michel, qui cite la preuve"
}]}"""

PROMPT_REPONSE = """Entretien avec Michel Moreau, pratique "{id}" : {titre}.
Preuve : {preuve}
Question posee : {question}
Reponse de Michel : "{reponse}"

{consigne}
Reponds uniquement avec ce JSON, sans texte autour :
{{"enregistre": true ou false, "contradiction": true ou false, "relance": "une question ou null", "resume": "une phrase ou null"}}"""

CONSIGNE_RELANCE = """Verifie d'abord la reponse dans les fichiers de donnees.
1. Si elle contredit les donnees, n'enregistre rien. Mets contradiction a true et pose une seule
relance respectueuse qui cite les chiffres exacts et un exemple du fichier.
2. Sinon, si elle ne donne pas une raison claire, n'enregistre rien et pose une seule relance precise.
3. Sinon, enregistre ce savoir avec ton outil de memoire (write_memory), dans savoir/{id}.md :
pratique, preuve, raison, condition, personne. Mets relance a null."""

CONSIGNE_FINALE = """N'ajoute pas de relance. Enregistre ce que Michel a dit avec ton outil de
memoire (write_memory), dans savoir/{id}.md : pratique, preuve, raison, condition, personne.
Note clairement ce qui reste inconnu et tout ecart avec les donnees."""

PROMPT_DOSSIER = """L'entretien est termine. Lis ta memoire, puis ecris le dossier de passation
de Michel Moreau pour sa remplacante, Camille. Pour chaque pratique : ce qu'il faut faire,
la raison, la condition, la preuve, et ce qui reste a verifier. Termine par les risques.
Reponds seulement avec le dossier, en Markdown. N'invente rien."""

PROMPT_PROCEDURE = """Lis ta memoire, puis propose une nouvelle version des 5 regles de la
procedure officielle. Garde le meme numero pour chaque regle. Ajoute les exceptions et leurs
conditions, comme Michel les a expliquees. Chaque regle fait 30 mots au maximum. N'invente rien.

Reponds uniquement avec ce JSON, sans texte autour :
{"regles": [{"numero": 1, "texte": "la nouvelle regle", "changement": "ce qui change, en une phrase", "source": "Michel Moreau, ou le fichier"}]}"""

PROMPT_REMPLACANT = """Je suis Camille, la remplacante de Michel Moreau. Lis ta memoire avant de
repondre. Reponds en peu de phrases : ce que je dois faire, pourquoi, et qui l'a dit.
Dis clairement ce que tu ne sais pas.

Ma question : {question}"""


@dataclass
class Session:
    namespace: str
    file_ids: list[str] = field(default_factory=list)
    thread_id: str | None = None
    replacant_thread_id: str | None = None
    pratiques: list[dict[str, Any]] = field(default_factory=list)
    relances: dict[str, int] = field(default_factory=dict)
    dossier_message_id: Any = None
    nouvelle_procedure: list[dict[str, Any]] = field(default_factory=list)
    procedure_validee: bool = False
    cout: Decimal = Decimal(0)


SESSIONS: dict[str, Session] = {}
app = FastAPI(title="Passation")


def make_client() -> AsyncCominty:
    return AsyncCominty(timeout=240)


def extraire_json(texte: str) -> dict[str, Any]:
    """Lit le dernier objet JSON d'une reponse, meme entoure de texte."""
    bloc = re.search(r"```(?:json)?\s*(\{.*\})\s*```", texte, re.S)
    candidat = bloc.group(1) if bloc else texte
    debut = candidat.find("{")
    if debut < 0:
        raise ValueError("Pas de JSON dans la reponse de l'agent.")
    decodeur = json.JSONDecoder()
    while debut >= 0:
        try:
            objet, _ = decodeur.raw_decode(candidat[debut:])
            if isinstance(objet, dict):
                return objet
        except json.JSONDecodeError:
            pass
        debut = candidat.find("{", debut + 1)
    raise ValueError("JSON illisible dans la reponse de l'agent.")


def libelle(event: Any) -> str | None:
    """Traduit un evenement Cominty en etape lisible pour l'interface."""
    if isinstance(event, events.SettingUpSandbox):
        return "Préparation de l'espace de travail"
    if isinstance(event, events.ToolCall) and event.status == "running":
        nom = event.data.name
        connus = {
            "read_file": "Lecture d'un document",
            "write_memory": "Écriture dans la mémoire",
            "update_memory": "Mise à jour de la mémoire",
            "read_memory": "Lecture de la mémoire",
            "list_memory": "Consultation de la mémoire",
            "execute": "Calcul sur les données",
        }
        return connus.get(nom, event.data.description or nom)
    return None


def ligne(objet: dict[str, Any]) -> str:
    return json.dumps(objet, ensure_ascii=False, default=str) + "\n"


async def suivre(run: Any, session: Session) -> AsyncIterator[str]:
    """Relaie les etapes de l'agent et additionne le cout reel."""
    async for event in run:
        texte = libelle(event)
        if texte:
            yield ligne({"t": "etape", "texte": texte})
        if isinstance(event, events.Result):
            session.cout += event.data.cost.total
            yield ligne({"t": "cout", "total": float(session.cout)})


def capacites(session: Session) -> AgentCapabilities:
    return AgentCapabilities(
        memory=MemoryCapability(activation="always", namespace=session.namespace)
    )


async def memoire(client: Any, session: Session) -> list[dict[str, str]]:
    """Lit la memoire reelle : l'interface ne croit pas l'agent sur parole."""
    fichiers = []
    for resume in await client.memory.list(namespace=session.namespace):
        complet = await client.memory.get(resume.path, namespace=session.namespace)
        fichiers.append({"chemin": complet.path, "contenu": complet.content or ""})
    return fichiers


def securise(flux: AsyncIterator[str]) -> StreamingResponse:
    async def enveloppe() -> AsyncIterator[str]:
        try:
            async for morceau in flux:
                yield morceau
        except ComintyError as e:
            yield ligne({"t": "erreur", "texte": f"Cominty a refusé l'action : {e}"})
        except ValueError as e:
            yield ligne({"t": "erreur", "texte": str(e)})

    return StreamingResponse(enveloppe(), media_type="application/x-ndjson")


def session_de(sid: str | None) -> Session:
    if not sid or sid not in SESSIONS:
        raise HTTPException(404, "Session inconnue. Lance une nouvelle enquête.")
    return SESSIONS[sid]


class Reponse(BaseModel):
    id: str = Field(max_length=120)
    texte: str = Field(min_length=1, max_length=2000)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.get("/api/procedures")
async def procedures() -> dict[str, list[str]]:
    lignes = (DOCS / "procedures.txt").read_text(encoding="utf-8").splitlines()
    regles = [re.sub(r"^\d\.\s*", "", l) for l in lignes if re.match(r"^\d\.", l)]
    return {"regles": regles}


@app.post("/api/session")
async def nouvelle_session() -> dict[str, str]:
    if len(SESSIONS) >= MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))
    sid = uuid.uuid4().hex
    SESSIONS[sid] = Session(namespace=f"passation-{sid[:12]}")
    return {"sid": sid}


@app.post("/api/enquete")
async def enquete(x_session: str | None = Header(default=None)) -> StreamingResponse:
    session = session_de(x_session)

    async def flux() -> AsyncIterator[str]:
        async with make_client() as client:
            session.file_ids = []
            for chemin in sorted(DOCS.iterdir()):
                yield ligne({"t": "etape", "texte": f"Envoi de {chemin.name}"})
                envoi = await client.chat.upload_file(
                    chemin.read_bytes(), filename=chemin.name, mimetype=TYPES[chemin.suffix]
                )
                session.file_ids.append(envoi.id)
            run = await client.chat.start(
                agent_id=AGENT_ID,
                message=PROMPT_ENQUETE,
                name="Enquête passation Michel Moreau",
                file_ids=session.file_ids,
                max_steps=30,
                thread_capabilities=capacites(session),
            )
            async for morceau in suivre(run, session):
                yield morceau
            reply = await run.result()
            session.thread_id = str(run.thread.id)
            session.pratiques = extraire_json(reply.content)["pratiques"][:5]
            yield ligne({"t": "enquete", "pratiques": session.pratiques})

    return securise(flux())


@app.post("/api/reponse")
async def reponse(corps: Reponse, x_session: str | None = Header(default=None)) -> StreamingResponse:
    session = session_de(x_session)
    pratique = next((p for p in session.pratiques if p["id"] == corps.id), None)
    if pratique is None:
        raise HTTPException(404, "Pratique inconnue.")

    async def flux() -> AsyncIterator[str]:
        relances = session.relances.get(corps.id, 0)
        modele = CONSIGNE_RELANCE if relances == 0 else CONSIGNE_FINALE
        message = PROMPT_REPONSE.format(
            id=pratique["id"],
            titre=pratique["titre"],
            preuve=pratique["preuve"],
            question=pratique["question"],
            reponse=corps.texte,
            consigne=modele.format(id=pratique["id"]),
        )
        async with make_client() as client:
            run = await client.chat.send(session.thread_id, agent_id=AGENT_ID, message=message)
            async for morceau in suivre(run, session):
                yield morceau
            verdict = extraire_json((await run.result()).content)
            fichiers = await memoire(client, session)
            trouve = any(corps.id in f["chemin"] for f in fichiers)

            if verdict.get("enregistre") and not trouve:
                yield ligne({"t": "etape", "texte": "Mémoire vide : l'agent recommence"})
                run = await client.chat.send(
                    session.thread_id,
                    agent_id=AGENT_ID,
                    message=(
                        f"Le fichier savoir/{corps.id}.md n'existe pas dans ta memoire. "
                        "Ecris-le maintenant avec write_memory. Reponds seulement : fait."
                    ),
                )
                async for morceau in suivre(run, session):
                    yield morceau
                await run.result()
                fichiers = await memoire(client, session)
                trouve = any(corps.id in f["chemin"] for f in fichiers)

            relance = verdict.get("relance")
            if isinstance(relance, str) and relance.lower() in {"", "null", "none"}:
                relance = None
            if trouve or relances >= 1:
                relance = None
            if relance:
                session.relances[corps.id] = relances + 1
            yield ligne(
                {
                    "t": "reponse",
                    "enregistre": trouve,
                    "relance": relance,
                    "contradiction": bool(relance and verdict.get("contradiction")),
                    "resume": verdict.get("resume"),
                    "memoire": fichiers,
                }
            )

    return securise(flux())


@app.post("/api/dossier")
async def dossier(x_session: str | None = Header(default=None)) -> StreamingResponse:
    session = session_de(x_session)

    async def flux() -> AsyncIterator[str]:
        async with make_client() as client:
            run = await client.chat.send(
                session.thread_id, agent_id=AGENT_ID, message=PROMPT_DOSSIER
            )
            async for morceau in suivre(run, session):
                yield morceau
            reply = await run.result()
            session.dossier_message_id = reply.id
            yield ligne({"t": "dossier", "markdown": reply.content})

    return securise(flux())


@app.post("/api/procedure")
async def procedure(x_session: str | None = Header(default=None)) -> StreamingResponse:
    session = session_de(x_session)

    async def flux() -> AsyncIterator[str]:
        async with make_client() as client:
            run = await client.chat.send(
                session.thread_id, agent_id=AGENT_ID, message=PROMPT_PROCEDURE
            )
            async for morceau in suivre(run, session):
                yield morceau
            regles = extraire_json((await run.result()).content)["regles"]
            session.nouvelle_procedure = sorted(regles, key=lambda r: r["numero"])[:5]
            yield ligne({"t": "procedure", "regles": session.nouvelle_procedure})

    return securise(flux())


@app.post("/api/procedure/valider")
async def valider_procedure(x_session: str | None = Header(default=None)) -> dict[str, Any]:
    session = session_de(x_session)
    if not session.nouvelle_procedure:
        raise HTTPException(404, "Fais d'abord proposer la nouvelle procédure.")
    if not session.procedure_validee:
        contenu = "\n".join(f'{r["numero"]}. {r["texte"]}' for r in session.nouvelle_procedure)
        async with make_client() as client:
            await client.memory.create(
                path="procedures/version-validee.md",
                namespace=session.namespace,
                purpose="Procédure commerciale validée par un humain",
                content=contenu,
            )
        session.procedure_validee = True
    return {"validee": True}


@app.get("/api/dossier.pdf")
async def dossier_pdf(s: str) -> Response:
    session = session_de(s)
    if session.dossier_message_id is None:
        raise HTTPException(404, "Écris d'abord le dossier.")
    async with make_client() as client:
        pdf = await client.chat.export(session.dossier_message_id, format="pdf")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="passation-michel-moreau.pdf"'},
    )


@app.post("/api/remplacant")
async def remplacant(corps: Question, x_session: str | None = Header(default=None)) -> StreamingResponse:
    session = session_de(x_session)

    async def flux() -> AsyncIterator[str]:
        message = PROMPT_REMPLACANT.format(question=corps.question)
        async with make_client() as client:
            if session.replacant_thread_id is None:
                run = await client.chat.start(
                    agent_id=AGENT_ID,
                    message=message,
                    name="Questions de Camille",
                    thread_capabilities=capacites(session),
                )
                session.replacant_thread_id = str(run.thread.id)
            else:
                run = await client.chat.send(
                    session.replacant_thread_id, agent_id=AGENT_ID, message=message
                )
            async for morceau in suivre(run, session):
                yield morceau
            reply = await run.result()
            yield ligne({"t": "remplacant", "texte": reply.content})

    return securise(flux())


@app.get("/")
async def accueil() -> FileResponse:
    return FileResponse(ICI / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ICI / "static"), name="static")
