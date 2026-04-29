# QuizBlitz API specifikācija

Flask REST API · JWT autentifikācija · SSE reāllaika notikumi · SQLite

**Bāzes URL:** `/api/v1`  
**Autentifikācija:** `Authorization: Bearer <token>`  
**H** = saimnieka JWT · **P** = dalībnieka JWT

---

## Autentifikācija

| Metode | Ceļš | Auth | Apraksts |
|--------|------|------|----------|
| `POST` | `/auth/login` | — | Pieslēgties. Ķermenis: `epasts`, `parole`. Atgriež `piekļuves_zetons`. |
| `POST` | `/auth/register` | — | Reģistrēties. `parole` min 8 zīmes. Atgriež `piekļuves_zetons`, statuss 201. |

---

## Viktorīnas

| Metode | Ceļš | Auth | Apraksts |
|--------|------|------|----------|
| `GET` | `/quizzes` | H | Visu piederošo viktorīnu saraksts ar kopsavilkumu. |
| `POST` | `/quizzes` | H | Izveidot viktorīnu. Ķermenis: `nosaukums`. Statuss: `MELNRAKSTS`. Atgriež 201. |
| `GET` | `/quizzes/:id` | H | Visa viktorīna ar jautājumiem un variantiem. |
| `PATCH` | `/quizzes/:id` | H | Labot: `nosaukums`, `apraksts`, `statuss`. |
| `DELETE` | `/quizzes/:id` | H | Dzēst viktorīnu (kaskādes). Atgriež 204. |

---

## Jautājumi

| Metode | Ceļš | Auth | Apraksts |
|--------|------|------|----------|
| `POST` | `/quizzes/:id/questions` | H | Pievienot jautājumu. Ķermenis: `teksts`, `tips` (`SINGLE_CHOICE` / `TRUE_FALSE`), `laika_limits_sekundes`, `punkti`, `atbilzu_varianti[]` (≥1 ar `pareizi: true`). |
| `PATCH` | `/questions/:id` | H | Labot tekstu, limitu, punktus vai aizstāt variantus. |
| `DELETE` | `/questions/:id` | H | Dzēst jautājumu. Atgriež 204. |

---

## Sesijas un spēle

| Metode | Ceļš | Auth | Apraksts |
|--------|------|------|----------|
| `POST` | `/sessions` | H | Izveidot sesiju. Ķermenis: `viktorinas_id`. Viktorīnai jābūt `PUBLICETS`. Atgriež `sesijas_id`, `pina_kods`. 201. |
| `GET` | `/sessions/:id` | H | Statuss, PIN, dalībnieku skaits. |
| `POST` | `/sessions/:id/start` | H | Sākt spēli (nepieciešams ≥1 dalībnieks). Nosūta pirmo jautājumu. |
| `POST` | `/sessions/:id/next-question` | H | Nākamais jautājums. Ja vairāk nav — beidz spēli. |
| `POST` | `/sessions/:id/end-question` | H | Manuāli beigt jautājumu. Izsūta pareizās atbildes + līderu tabulu. |
| `POST` | `/sessions/:id/end-game` | H | Piespiedu kārtā beigt spēli. Atgriež gala līderu tabulu. |

---

## Spēlētāju maršruti

| Metode | Ceļš | Auth | Apraksts |
|--------|------|------|----------|
| `POST` | `/join` | — | Atrast sesiju pēc PIN. Ķermenis: `pina_kods`. Atgriež `sesijas_id`. |
| `POST` | `/join/:sid/identify` | — | Pievienoties. Ķermenis: `segvards`. Atgriež `dalibnieka_zetons`. |
| `POST` | `/answer` | P | Iesniegt atbildi. Ķermenis: `opcijas_id`. Atgriež `pareizi`, `iegutie_punkti`, `kopejie_punkti`. |
| `GET` | `/participant/state` | P | Pašreizējais stāvoklis: aktīvais jautājums, atlikušais laiks, punkti. |

---

## SSE reāllaika plūsma

```
GET /sessions/:id/events
```

Nav autentifikācijas. Saglabā savienojumu atvērtu. Heartbeat ik 25 s.

| Notikums | Apraksts |
|----------|----------|
| `sesijas_stavoklis` | Sākotnējais stāvoklis pievienojoties: statuss, PIN, dalībnieku saraksts. |
| `gaiditava_dalibnieks_pievienojies` | Jauns spēlētājs. Dati: `id`, `segvards`. |
| `gaiditava_dalibnieki` | Pilns dalībnieku saraksts pēc katra pievienošanās. |
| `spele_sakusies` | Saimnieks uzsācis spēli. |
| `spele_jautajums_sakas` | Jauns jautājums — teksts, varianti, laika limits, punkti. |
| `atbilde_apstiprinata` | Spēlētājs atbildēja — pareizums, punkti, laiks. |
| `spele_jautajums_beidzas` | Pareizās atbildes un statistika pēc jautājuma. |
| `spele_lideru_tabula` | Pašreizējā līderu tabula. |
| `spele_beigusies` | Spēle beigusies — gala līderu tabula. |

---

## Kļūdu kodi

| HTTP | `kludas_kods` | Situācija |
|------|---------------|-----------|
| 400 | `SLIKTS_PIEPRASIJUMS` | Trūkst lauka, nepareizs statuss, dublikāts u.c. |
| 401 | `NAV_AUTORIZETS` | Trūkst vai beidzies JWT. |
| 401 | `NEPAREIZAS_PIESAISTES` | Nepareizs e-pasts vai parole. |
| 403 | `NAV_PIEKLUVE` | Resurss pieder citam lietotājam. |
| 404 | `NAV_ATRASTS` | Resurss neeksistē. |
| 409 | `KONFLIKTS` | E-pasts vai segvārds jau aizņemts. |

---

## Statusi

| API vērtība | DB vērtība | Nozīme |
|-------------|------------|--------|
| `MELNRAKSTS` | `DRAFT` | Rediģēšanas režīms, nevar sākt sesiju. |
| `PUBLICETS` | `PUBLISHED` | Gatava spēlei. |
| `GAIDA` | `WAITING` | Sesija atvērta, gaida spēlētājus. |
| `NOTIEK` | `ACTIVE` | Spēle notiek. |
| `PABEIGTS` | `FINISHED` | Spēle beigusies. |
