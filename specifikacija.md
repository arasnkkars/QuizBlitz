# QuizBlitz — datu specifikācija

Lietotāja saskarne (`templates/`, `static/`) un **HTTP/SSE JSON lauku nosaukumi** API atbildēs ir **latviešu valodā** (izņemot iekšējās vērtības kā `SINGLE_CHOICE`, JWT `exp`). SQLite kolonnu nosaukumi joprojām ir **angliski** (`title`, `email`, u. c.); serveris tulkojumu veic JSON robežā (`main.py`).

Projekts nodrošina tiešsaistes viktorīnu izveidi, publicēšanu un spēli ar spēlētāju paneļiem. Šajā dokumentā apkopoti **glabātie dati** un **REST API izvaddatu** (JSON lauku nosaukumi un loģiskie tipi).

---

## 1. SQLite datubāze (`quizblitz.db`)

| Tabula | Lauks | Tips | Piezīmes |
|--------|-------|------|-----------|
| `users` | `id` | `TEXT` (UUID) | Primārā atslēga |
| | `email` | `TEXT` | Unikāls; mazajiem burtiem |
| | `password_hash` | `TEXT` | SHA-256 heksadecimali no paroles |
| `quizzes` | `id` | `TEXT` (UUID) | Primārā atslēga |
| | `owner_id` | `TEXT` | Atsauce uz `users.id` |
| | `title` | `TEXT` | Nosaukums |
| | `description` | `TEXT` | Apraksts |
| | `status` | `TEXT` | `DRAFT` \| `PUBLISHED` |
| | `created_at`, `updated_at` | `TEXT` | ISO 8601 UTC ar `Z` |
| `questions` | `id` | `TEXT` (UUID) | Primārā atslēga |
| | `quiz_id` | `TEXT` | Atsauce uz `quizzes.id`, `ON DELETE CASCADE` |
| | `text` | `TEXT` | Jautājuma formulējums |
| | `type` | `TEXT` | Piem. `SINGLE_CHOICE`, `TRUE_FALSE` |
| | `time_limit_seconds` | `INTEGER` | Laika limits sekundēs |
| | `points` | `INTEGER` | Punkti par pareizu atbildi |
| | `order_index` | `INTEGER` | Secība viktorīnā |
| `answer_options` | `id` | `TEXT` (UUID) | Primārā atslēga |
| | `question_id` | `TEXT` | Atsauce uz `questions.id`, `ON DELETE CASCADE` |
| | `text` | `TEXT` | Atbildes variants |
| | `is_correct` | `INTEGER` | `0` vai `1` (SQLite booleāns) |
| | `order_index` | `INTEGER` | Secība |
| `sessions` | `id` | `TEXT` (UUID) | Sesijas ID |
| | `pin` | `TEXT` | 6 ciparu PIN |
| | `quiz_id` | `TEXT` | Atsauce uz `quizzes.id` |
| | `host_id` | `TEXT` | Atsauce uz `users.id` |
| | `status` | `TEXT` | `WAITING` \| `ACTIVE` \| `FINISHED` |
| | `current_question_index` | `INTEGER` | Aktīvā jautājuma indekss (−1 pirms spēles) |
| | `question_start_time` | `REAL` \| `NULL` | Unix laiks sekundēs (`time.time()`) |
| | `created_at` | `TEXT` | ISO laiks |
| `participants` | `id` | `TEXT` (UUID) | Dalībnieka ID |
| | `session_id` | `TEXT` | Atsauce uz `sessions.id` |
| | `nickname` | `TEXT` | Segvārds |
| | `score` | `INTEGER` | Kopējie punkti |
| | `connected` | `INTEGER` | `0`/`1` |
| | `answers_json` | `TEXT` | JSON objekts: `jautājuma_id` → `opcijas_id` vai `null` |

---

## 2. API izvaddati (JSON)

Visas atbildes, kur nav norādīts īpaši, ir `application/json`. Kļūdu struktūra:

```json
{
  "statusa_kods": 404,
  "kludas_kods": "NAV_ATRASTS",
  "zinojums": "…",
  "laika_zime": "2026-04-28T12:00:00.000000Z"
}
```

### 2.1 Autentifikācija

| Ceļš | Izvade (veiksme) | Svarīgi lauki |
|------|-------------------|---------------|
| `POST /api/v1/auth/login` | `200` | `piekļuves_zetons`: `string` (JWT), `lietotajs`: `{ id, epasts }`; pieprasījumā `epasts`, `parole` |
| `POST /api/v1/auth/register` | `201` | Tāpat kā login |

JWT saturs (payload): saimniekam — `lietotaja_id`, `epasts`, `exp`; dalībniekam — `dalibnieka_id`, `sesijas_id`, `exp`.

### 2.2 Saimnieka viktorīnas

| Ceļš | Izvade | Piezīmes |
|------|--------|-----------|
| `GET /api/v1/quizzes` | `array` | Katram: `id`, `nosaukums`, `statuss` (`MELNRAKSTS` \| `PUBLICETS`), `skaits.jautajumi`, `jautajumi[]` (īss: `id`, `teksts`), … |
| `POST /api/v1/quizzes` | `201` | `nosaukums` pieprasījumā; atbilde kā saraksta elements |
| `GET /api/v1/quizzes/<id>` | `200` | `jautajumi[]` ar `atbilzu_varianti[]` (`id`, `teksts`, `pareizi`, `kartiba`) |
| `PATCH /api/v1/quizzes/<id>` | `200` | `nosaukums`, `apraksts`, `statuss` (`MELNRAKSTS` \| `PUBLICETS`) |
| `DELETE /api/v1/quizzes/<id>` | `204` | Bez ķermeņa |

### 2.3 Jautājumi

| Ceļš | Izvade |
|------|--------|
| `POST .../questions` | `201` — jauns jautājums (latviskie lauki) |
| `PATCH /api/v1/questions/<id>` | `200` — jautājums |
| `DELETE ...` | `204` |

Pievienošanai: `teksts`, `tips`, `laika_limits_sekundes`, `punkti`, `atbilzu_varianti[]` (`teksts`, `pareizi`).

### 2.4 Sesija un spēle

| Ceļš | Izvade | Lauki |
|------|--------|-------|
| `POST /api/v1/sessions` | `201` | `sesijas_id`, `pina_kods`; pieprasījumā `viktorinas_id` |
| `GET /api/v1/sessions/<id>` | `200` | `id`, `pina_kods`, `statuss`, `viktorinas_nosaukums`, `dalibnieku_skaits` |
| `POST /api/v1/join` | `200` | `sesijas_id`, `viktorinas_nosaukums`; `pina_kods` pieprasījumā |
| `POST /api/v1/join/<sid>/identify` | `200` | `dalibnieka_zetons`, `dalibnieka_id`, `segvards` |
| `POST .../start`, `next-question`, `end-question`, `end-game` | `200` / kļūda | Atkarībā no spēles fāzes |
| `POST /api/v1/answer` | `200` | `pareizi`, `iegutie_punkti`, `kopejie_punkti`, `pagajusas_sekundes`; `opcijas_id` pieprasījumā |
| `GET /api/v1/participant/state` | `200` | `sesijas_stavoklis`, `pasreizejais_jautajums`, `atbildets_uz_pasreizejo`, `punkti` |

### 2.5 Server-Sent Events

`GET /api/v1/sessions/<id>/events` — teksta plūsma `text/event-stream`; katras ziņas ķermenis ir JSON:

```json
{ "notikums": "string", "dati": { } }
```

Piemēri: `sesijas_stavoklis`, `gaiditava_dalibnieki`, `spele_jautajums_sakas`, `spele_jautajums_beidzas`, `spele_lideru_tabula`, `spele_beigusies`, `atbilde_apstiprinata`.

---

## 3. Ārējās atkarības (no `requirements.txt`)

Skat. `README.md` sadaļu *Licences*.
