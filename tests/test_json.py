from main import extraire_json


def test_json_entoure_de_texte():
    texte = 'The answer is vague.\n\n{"enregistre": false, "relance": "Pourquoi {cela} ?", "resume": null}'
    assert extraire_json(texte)["relance"] == "Pourquoi {cela} ?"


def test_json_bloc_code():
    assert extraire_json('```json\n{"pratiques": [1]}\n```')["pratiques"] == [1]


def test_json_apres_accolades_en_texte():
    assert extraire_json('Note {pas du json}\n{"enregistre": true}')["enregistre"] is True
