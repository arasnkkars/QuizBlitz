"""
Akceptācijas testi — vismaz trīs scenāriji pret Flask test_client.

Pirms `main` importa jāiestata QUIZBLITZ_DB_PATH, lai testi nelieto ražošanas failu.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["QUIZBLITZ_DB_PATH"] = _tmp.name

from main import app  # noqa: E402


class TestAkceptacija(unittest.TestCase):
    """Spēļu API pamatplūsmu pārbaude."""

    def setUp(self) -> None:
        self.client = app.test_client()

    def test_1_demo_pieslegšanas_speja(self) -> None:
        """Derīgas apliecības iegūšana ar demonstrācijas kontu."""
        atbilde = self.client.post(
            "/api/v1/auth/login",
            json={"epasts": "demo@quiz.com", "parole": "password123"},
        )
        self.assertEqual(atbilde.status_code, 200)
        dati = atbilde.get_json()
        self.assertIsNotNone(dati.get("piekļuves_zetons"))
        self.assertEqual(dati["lietotajs"]["epasts"], "demo@quiz.com")

    def test_2_quiz_izveide_un_iegusana(self) -> None:
        """Pēc pierakstīšanās viktorīnas izveide un tās nolasīšana."""
        tok = self.client.post(
            "/api/v1/auth/login",
            json={"epasts": "demo@quiz.com", "parole": "password123"},
        ).get_json()["piekļuves_zetons"]
        virsraksts = f"Akcepts-{uuid.uuid4().hex[:8]}"
        radits = self.client.post(
            "/api/v1/quizzes",
            json={"nosaukums": virsraksts},
            headers={"Authorization": f"Bearer {tok}"},
        )
        self.assertEqual(radits.status_code, 201)
        qid = radits.get_json()["id"]
        nolasits = self.client.get(
            f"/api/v1/quizzes/{qid}",
            headers={"Authorization": f"Bearer {tok}"},
        )
        self.assertEqual(nolasits.status_code, 200)
        self.assertEqual(nolasits.get_json()["nosaukums"], virsraksts)

    def test_3_registracija_dublikata_konflikts(self) -> None:
        """Otrais reģistrācijas mēģinājums ar to pašu e-pastu dod 409."""
        epasts = f"unikals_{uuid.uuid4().hex[:12]}@test.lv"
        parole = "astardejošaParole8"
        pirmais = self.client.post(
            "/api/v1/auth/register",
            json={"epasts": epasts, "parole": parole},
        )
        self.assertEqual(pirmais.status_code, 201)
        otrais = self.client.post(
            "/api/v1/auth/register",
            json={"epasts": epasts, "parole": parole},
        )
        self.assertEqual(otrais.status_code, 409)
        dati = otrais.get_json()
        self.assertEqual(dati.get("kludas_kods"), "KONFLIKTS")

    def test_4_kludas_atsauce_neeksistejosam_kvizam(self) -> None:
        """Kļūdas JSON struktūra (atkļūdošanai paredzētais vienotais formāts)."""
        tok = self.client.post(
            "/api/v1/auth/login",
            json={"epasts": "demo@quiz.com", "parole": "password123"},
        ).get_json()["piekļuves_zetons"]
        atbilde = self.client.get(
            "/api/v1/quizzes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {tok}"},
        )
        self.assertEqual(atbilde.status_code, 404)
        dati = atbilde.get_json()
        self.assertIn("statusa_kods", dati)
        self.assertIn("kludas_kods", dati)
        self.assertIn("zinojums", dati)
        self.assertIn("laika_zime", dati)


if __name__ == "__main__":
    unittest.main()
