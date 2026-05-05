# MediNet — Sistem Integrat de Gestiune Medicală (Bază de date distribuită)

Aplicație web care implementează în mod realist arhitectura distribuită
descrisă în specificație: o rețea de tip **Hub-and-Spoke** cu un sediu
central (`S1 — GLOBAL_DB`) și trei filiale regionale (`S2 — LOCAL_SUD`,
`S3 — LOCAL_VEST`, `S4 — LOCAL_EST`).

Fiecare „nod” este o bază de date SQLite separată (`data/global.db`,
`data/local_sud.db`, `data/local_vest.db`, `data/local_est.db`), iar
backend-ul Flask deschide câte o conexiune dedicată pentru fiecare —
exact ca un sistem distribuit real. Nu există un schimb implicit de
tabele între ele; orice JOIN, UNION, FK sau replicare este implementat
în mod explicit la nivelul aplicației, simulând DB Link / triggere
distribuite Oracle.

## Stack tehnologic

- **Backend:** Python 3.12 + Flask 3
- **Storage:** 4× SQLite (un fișier per nod al rețelei)
- **Frontend:** HTML + CSS modern (vanilla) + JavaScript ES6 (fără build)
- **Comunicare:** REST/JSON

## Caracteristici implementate

| Cerință din specificație | Implementare |
|---|---|
| Fragmentare orizontală primară (PACIENT pe regiune) | Pacientul este rutat către S2/S3/S4 în funcție de `regiune` |
| Fragmentare orizontală derivată (PROGRAMARE / FACTURA / PROG_DIAG) | Inserate pe nodul „home” al pacientului (semi-join logic) |
| Fragmentare verticală (MEDIC) | `MEDIC_OP` (replicat S2/S3/S4 + S1) și `MEDIC_HR` (exclusiv S1) |
| Replicare completă nomenclatoare | `DIAGNOSTIC`, `TRATAMENT`, `SPECIALIZARE`, `SECTIE` pe toate nodurile |
| Sincronizare via „trigger distribuit” | INSERT / UPDATE / DELETE pe S2 (master) propagat către S3 / S4 / S1 |
| Transparența localizării | View-uri globale `V_PACIENTI_COMPLET`, `V_PROGRAMARE_COMPLET`, `V_FACTURA_COMPLET`, `V_MEDIC_COMPLET` |
| Unicitate globală CNP | Catalog global pe S1 verificat înainte de orice INSERT pacient |
| Unicitate globală pe fragmente verticale | Validare `nume + prenume + data_angajarii` pe S1 înainte de inserare medic |
| Cheie primară globală (HF) | Secvențe per-nod cu plaje disjuncte (1.000.000 / 2.000.000 / 3.000.000) |
| FK distribuit (PROGRAMARE → PACIENT) | Verifică existența pacientului în toate nodurile locale înainte de INSERT |
| Validare distribuită (mărire salariu) | Blochează `UPDATE MEDIC_HR.salariu` dacă există facturi `Restant` |
| Cerere OLAP complexă | „Performanța medicilor pe diagnostic” cu 3 strategii de execuție |
| Optimizare RBO vs CBO vs PARALLEL | Toate cele trei strategii sunt rulate paralel și comparate (durată + rânduri prin rețea) |

## Cum rulezi

```bash
pip install -r requirements.txt
python3 app.py
```

Apoi deschide [http://localhost:5000](http://localhost:5000).

La prima pornire, schemele și datele demo sunt create automat. Folosește
butonul „Reset demo” din UI pentru a reinițializa rețeaua.

## Tab-urile aplicației

1. **Privire de ansamblu** — topologie, KPI-uri, status pe fiecare nod.
2. **Pacienți** — formular cu rutare automată + view global cu filtru pe nod.
3. **Programări & Facturi** — inserare cu FK distribuit + view-uri globale.
4. **Medici (HR)** — adăugare cu unicitate verticală globală + modificare
   salariu cu validare distribuită cross-node.
5. **Nomenclatoare** — adăugare DIAGNOSTIC pe nodul master (S2) și
   verificare că s-a propagat instant pe S1, S3, S4.
6. **Raport OLAP** — cele 3 strategii (Sequential / Hash Join / Parallel +
   Semi-Join), fiecare cu numărul de rânduri transferate prin rețea și
   durata de execuție.
7. **Jurnal interogări** — log live al fiecărei comenzi SQL cu nodul
   țintă, tipul (REPLICATION, FK CHECK, PARALLEL AGG, ...) și durata.

## Structura proiectului

```
.
├── app.py                # Flask app + REST API
├── database.py           # Connection layer + fragmentare + replicare + raport
├── requirements.txt
├── data/                 # Bazele de date SQLite (create la rulare)
├── static/
│   ├── app.js
│   └── style.css
└── templates/
    └── index.html
```
