# QuizBlitz

Tiešsaistes viktorīnu platforma (Flask + SQLite + vienlapas saskarne). **Saskarne un kļūdu ziņojumi lietotājam — latviešu valodā.**

## Palaišana

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

Demonstrācijas konts: `demo@quiz.com` / `password123`.

Datubāzes failu nosaka vides mainīgais `QUIZBLITZ_DB_PATH` (pēc noklusējuma `quizblitz.db` blakus `main.py`).

## Testi (akceptācija)

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Testi izmanto atsevišķu pagaidu SQLite failu (iestatīts `tests/test_akcepts.py` iekšā).

## Dokumentācija

- `specifikacija.md` — datu bāzes lauki un REST API izvaddatu tipi (JSON).
- `LICENSE` — šī projekta licences teksts (MIT).

## Licences (pamatojums)

| Komponente | Licence | Kāpēc piemērota |
|------------|---------|------------------|
| **Šis projekts** | [MIT](LICENSE) | Ļauj brīvi izmantot mācību un demonstrācijas nolūkos ar nelielu autortiesību norādi. |
| **Flask** | [BSD-3-Clause](https://github.com/pallets/flask/blob/main/LICENSE.txt) | Stabil HTTP serveris Python projektiem; licence atļauj komerciālu un privātu lietošanu. |
| **PyJWT** | [MIT](https://github.com/jpadilla/pyjwt/blob/master/LICENSE) | Saderīga ar šī projekta MIT; JWT veidošanai/verifikācijai. |

Atkarību īpašnieku licences nosaka to oficiālie avoti; `requirements.txt` norāda versijas, nevis juridisko tekstu.
