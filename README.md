# Passation

Quand un employé expérimenté part, une partie de son savoir part avec lui.
Passation lit son travail, repère les règles que personne n'a écrites, l'interroge
sur chacune, garde ses réponses, puis aide son remplaçant.

## Ce que fait l'agent

1. Il compare les procédures aux devis, achats, expéditions et e-mails.
2. Il calcule les faits et trouve les pratiques non écrites.
3. Il mène l'entretien, une question à la fois, et relance si la réponse est vague.
4. Il écrit chaque savoir dans la mémoire Cominty.
5. Il rédige le dossier de passation, exportable en PDF.
6. Dans une nouvelle conversation, il répond au remplaçant depuis la mémoire.

## Intégration Cominty

| Fonction | Usage |
|---|---|
| Managed Agent | Agent Passation avec ses instructions |
| `chat.upload_file` | Envoi des 5 documents |
| Flux d'événements | Étapes en direct et coût réel à l'écran |
| `MemoryCapability` | Une mémoire par session, partagée entre conversations |
| `client.memory` | L'application vérifie la mémoire au lieu de croire l'agent |
| `chat.export` | Dossier en PDF |

## Lancer

```powershell
$env:COMINTY_API_KEY="..."
$env:COMINTY_USER_ID="user_..."
.\lancer.ps1
```

L'identifiant d'agent par défaut est modifiable avec `COMINTY_AGENT_ID`.
Toutes les données de démonstration sont fictives.
