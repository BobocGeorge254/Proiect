"""
Distributed Database Layer pentru Sistemul Integrat de Gestiune Medicala.

Simuleaza 4 noduri ale unei baze de date distribuite folosind 4 fisiere SQLite
separate (cate o conexiune dedicata pentru fiecare):

    S1 - GLOBAL_DB  -> data/global.db   (Sediu Central)
    S2 - LOCAL_SUD  -> data/local_sud.db
    S3 - LOCAL_VEST -> data/local_vest.db
    S4 - LOCAL_EST  -> data/local_est.db

Strategia de distribuire:
    * Fragmentare orizontala primara: PACIENT pe regiune (Sud / Vest / Est).
    * Fragmentare orizontala derivata: PROGRAMARE, FACTURA, PROG_DIAG.
    * Fragmentare verticala: MEDIC_OP (replicat pe S2/S3/S4) si MEDIC_HR (doar S1).
    * Replicare completa: SECTIE, SPECIALIZARE, DIAGNOSTIC, TRATAMENT, MEDIC_OP.

Schemele si view-urile globale sunt construite pentru a oferi transparenta
fragmentarii catre stratul aplicatiei (vezi app.py).
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Sequence, Tuple

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

NODES: Dict[str, Dict[str, str]] = {
    "S1": {"user": "GLOBAL_DB", "label": "Sediu Central (Global)", "file": "global.db"},
    "S2": {"user": "LOCAL_SUD", "label": "Filiala Sud", "file": "local_sud.db", "regiune": "Sud"},
    "S3": {"user": "LOCAL_VEST", "label": "Filiala Vest", "file": "local_vest.db", "regiune": "Vest"},
    "S4": {"user": "LOCAL_EST", "label": "Filiala Est", "file": "local_est.db", "regiune": "Est"},
}

LOCAL_NODES: Tuple[str, ...] = ("S2", "S3", "S4")

REGION_TO_NODE: Dict[str, str] = {
    "Sud": "S2",
    "Vest": "S3",
    "Est": "S4",
}

NODE_TO_REGION: Dict[str, str] = {v: k for k, v in REGION_TO_NODE.items()}


# ---------------------------------------------------------------------------
# Conexiuni
# ---------------------------------------------------------------------------

_connections: Dict[str, sqlite3.Connection] = {}


def _connect(node: str) -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, NODES[node]["file"])
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_conn(node: str) -> sqlite3.Connection:
    if node not in _connections:
        _connections[node] = _connect(node)
    return _connections[node]


def close_all() -> None:
    for c in _connections.values():
        try:
            c.close()
        except Exception:
            pass
    _connections.clear()


@contextmanager
def timed():
    start = time.perf_counter()
    bucket: Dict[str, float] = {}
    try:
        yield bucket
    finally:
        bucket["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)


# ---------------------------------------------------------------------------
# Utilitare interogare cu jurnalizare
# ---------------------------------------------------------------------------

QUERY_LOG: List[Dict] = []
MAX_LOG = 200


def _log(node: str, sql: str, params: Sequence | None = None, elapsed_ms: float | None = None,
         rows: int | None = None, kind: str = "SQL") -> None:
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "node": node,
        "user": NODES[node]["user"],
        "sql": " ".join(sql.split()),
        "params": list(params) if params else [],
        "elapsed_ms": elapsed_ms,
        "rows": rows,
        "kind": kind,
    }
    QUERY_LOG.append(entry)
    if len(QUERY_LOG) > MAX_LOG:
        del QUERY_LOG[: len(QUERY_LOG) - MAX_LOG]


def exec_sql(node: str, sql: str, params: Sequence | None = None, *, kind: str = "SQL") -> sqlite3.Cursor:
    conn = get_conn(node)
    start = time.perf_counter()
    cur = conn.execute(sql, tuple(params) if params else ())
    elapsed = round((time.perf_counter() - start) * 1000, 3)
    _log(node, sql, params, elapsed, cur.rowcount if cur.rowcount != -1 else None, kind)
    return cur


def query(node: str, sql: str, params: Sequence | None = None, *, kind: str = "SQL") -> List[sqlite3.Row]:
    cur = exec_sql(node, sql, params, kind=kind)
    rows = cur.fetchall()
    if QUERY_LOG:
        QUERY_LOG[-1]["rows"] = len(rows)
    return rows


def executemany(node: str, sql: str, seq: Iterable[Sequence], *, kind: str = "SQL BULK") -> None:
    conn = get_conn(node)
    start = time.perf_counter()
    seq = list(seq)
    conn.executemany(sql, seq)
    elapsed = round((time.perf_counter() - start) * 1000, 3)
    _log(node, sql, [f"<{len(seq)} batch rows>"], elapsed, len(seq), kind)


# ---------------------------------------------------------------------------
# Initializare schema
# ---------------------------------------------------------------------------

REPLICATED_SCHEMA = """
CREATE TABLE IF NOT EXISTS SECTIE (
    id_sectie    INTEGER PRIMARY KEY,
    denumire     TEXT NOT NULL,
    etaj         INTEGER,
    numar_paturi INTEGER
);

CREATE TABLE IF NOT EXISTS SPECIALIZARE (
    id_specializare INTEGER PRIMARY KEY,
    denumire        TEXT NOT NULL,
    descriere       TEXT
);

CREATE TABLE IF NOT EXISTS DIAGNOSTIC (
    id_diagnostic INTEGER PRIMARY KEY,
    cod_boala     TEXT UNIQUE NOT NULL,
    nume          TEXT NOT NULL,
    severitate    TEXT CHECK (severitate IN ('Scazut', 'Mediu', 'Critic'))
);

CREATE TABLE IF NOT EXISTS TRATAMENT (
    id_tratament   INTEGER PRIMARY KEY,
    denumire       TEXT NOT NULL,
    tip            TEXT,
    cost_referinta REAL
);

CREATE TABLE IF NOT EXISTS MEDIC_OP (
    id_medic   INTEGER PRIMARY KEY,
    nume       TEXT NOT NULL,
    prenume    TEXT NOT NULL,
    cod_parafa TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS MEDIC_SPECIALIZARI (
    id_medic_spec   INTEGER PRIMARY KEY,
    id_medic        INTEGER NOT NULL REFERENCES MEDIC_OP(id_medic),
    id_specializare INTEGER NOT NULL REFERENCES SPECIALIZARE(id_specializare)
);

CREATE TABLE IF NOT EXISTS MEDIC_SECTII (
    id_medic_sectii INTEGER PRIMARY KEY,
    id_medic        INTEGER NOT NULL REFERENCES MEDIC_OP(id_medic),
    id_sectie       INTEGER NOT NULL REFERENCES SECTIE(id_sectie)
);
"""

LOCAL_FRAGMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS PACIENTI_LOCAL (
    id_pacient    INTEGER PRIMARY KEY,
    nume          TEXT,
    prenume       TEXT,
    cnp           TEXT UNIQUE,
    data_nasterii TEXT,
    gen           TEXT CHECK (gen IN ('Masculin', 'Feminin')),
    regiune       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PROGRAMARE_LOCAL (
    id_programare INTEGER PRIMARY KEY,
    id_pacient    INTEGER NOT NULL REFERENCES PACIENTI_LOCAL(id_pacient),
    id_medic      INTEGER NOT NULL REFERENCES MEDIC_OP(id_medic),
    id_tratament  INTEGER REFERENCES TRATAMENT(id_tratament),
    data_ora      TEXT NOT NULL,
    durata_min    INTEGER DEFAULT 30,
    status        TEXT DEFAULT 'Programat'
);

CREATE TABLE IF NOT EXISTS FACTURA_LOCAL (
    id_factura    INTEGER PRIMARY KEY,
    id_programare INTEGER NOT NULL REFERENCES PROGRAMARE_LOCAL(id_programare),
    data_emitere  TEXT NOT NULL,
    suma          REAL NOT NULL CHECK (suma >= 0),
    status_plata  TEXT CHECK (status_plata IN ('Platit', 'Restant', 'Anulat'))
);

CREATE TABLE IF NOT EXISTS PROG_DIAG_LOCAL (
    id_prog_diag   INTEGER PRIMARY KEY,
    id_programare  INTEGER REFERENCES PROGRAMARE_LOCAL(id_programare),
    id_diagnostic  INTEGER REFERENCES DIAGNOSTIC(id_diagnostic),
    este_principal INTEGER CHECK (este_principal IN (0, 1))
);

CREATE TABLE IF NOT EXISTS SEQ_LOCAL (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

GLOBAL_EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS MEDIC_HR (
    id_medic       INTEGER PRIMARY KEY,
    data_angajarii TEXT NOT NULL,
    salariu        REAL NOT NULL CHECK (salariu >= 0)
);

CREATE TABLE IF NOT EXISTS CATALOG_GLOBAL (
    cnp     TEXT PRIMARY KEY,
    node    TEXT NOT NULL,
    regiune TEXT NOT NULL
);
"""


def init_schemas() -> None:
    """Creeaza schemele pe toate cele 4 noduri."""
    for node in LOCAL_NODES:
        conn = get_conn(node)
        conn.executescript(REPLICATED_SCHEMA)
        conn.executescript(LOCAL_FRAGMENTS_SCHEMA)
        _log(node, "-- DDL: schema locala (replicate + fragmente orizontale)", kind="DDL")
        conn.execute("INSERT OR IGNORE INTO SEQ_LOCAL(name, value) VALUES (?, ?)",
                     ("seq_pacient", _seq_start(node, "pacient")))
        conn.execute("INSERT OR IGNORE INTO SEQ_LOCAL(name, value) VALUES (?, ?)",
                     ("seq_programare", _seq_start(node, "programare")))
        conn.execute("INSERT OR IGNORE INTO SEQ_LOCAL(name, value) VALUES (?, ?)",
                     ("seq_factura", _seq_start(node, "factura")))
        conn.execute("INSERT OR IGNORE INTO SEQ_LOCAL(name, value) VALUES (?, ?)",
                     ("seq_prog_diag", _seq_start(node, "prog_diag")))

    g = get_conn("S1")
    g.executescript(REPLICATED_SCHEMA)
    g.executescript(GLOBAL_EXTRA_SCHEMA)
    _log("S1", "-- DDL: schema globala (replicate + MEDIC_HR + CATALOG_GLOBAL)", kind="DDL")


def _seq_start(node: str, name: str) -> int:
    base = {"S2": 1_000_000, "S3": 2_000_000, "S4": 3_000_000}[node]
    offsets = {"pacient": 0, "programare": 1000, "factura": 2000, "prog_diag": 3000}
    return base + offsets[name]


def next_id(node: str, seq_name: str) -> int:
    """Asigura unicitate globala pentru cheile primare ale fragmentelor orizontale."""
    conn = get_conn(node)
    cur = conn.execute("UPDATE SEQ_LOCAL SET value = value + 1 WHERE name = ?", (seq_name,))
    if cur.rowcount == 0:
        raise RuntimeError(f"Secventa {seq_name} nu exista pe nodul {node}")
    row = conn.execute("SELECT value FROM SEQ_LOCAL WHERE name = ?", (seq_name,)).fetchone()
    return int(row["value"])


# ---------------------------------------------------------------------------
# Replicare nomenclatoare (sincronizare 'trigger' la nivel de aplicatie)
# ---------------------------------------------------------------------------

REPLICATED_TABLES = ("SECTIE", "SPECIALIZARE", "DIAGNOSTIC", "TRATAMENT",
                     "MEDIC_OP", "MEDIC_SPECIALIZARI", "MEDIC_SECTII")


def replicate_to_all(table: str, columns: Sequence[str], values: Sequence,
                     master_node: str = "S2") -> None:
    """Insereaza pe nodul master apoi propaga catre celelalte noduri locale + S1.

    Simuleaza triggerul AFTER INSERT distribuit din specificatie.
    """
    placeholders = ",".join(["?"] * len(columns))
    cols_sql = ",".join(columns)
    sql = f"INSERT OR REPLACE INTO {table} ({cols_sql}) VALUES ({placeholders})"
    targets = [master_node] + [n for n in (LOCAL_NODES + ("S1",)) if n != master_node]
    for n in targets:
        exec_sql(n, sql, values, kind=f"REPLICATION -> {n}")


def update_replicated(table: str, set_clause: str, where_clause: str,
                      params: Sequence) -> None:
    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
    for n in LOCAL_NODES + ("S1",):
        exec_sql(n, sql, params, kind=f"REPLICATION UPDATE -> {n}")


def delete_replicated(table: str, where_clause: str, params: Sequence) -> None:
    sql = f"DELETE FROM {table} WHERE {where_clause}"
    for n in LOCAL_NODES + ("S1",):
        exec_sql(n, sql, params, kind=f"REPLICATION DELETE -> {n}")


# ---------------------------------------------------------------------------
# Operatii pe MEDIC (fragmentare verticala)
# ---------------------------------------------------------------------------

def insert_medic(id_medic: int, nume: str, prenume: str, cod_parafa: str,
                 data_angajarii: str, salariu: float) -> None:
    """Implementeaza unicitatea globala (nume+prenume+data_angajarii) pe S1
    inainte de a propaga fragmentul MEDIC_OP catre nodurile locale.
    """
    rows = query(
        "S1",
        """
        SELECT 1
        FROM MEDIC_OP op
        JOIN MEDIC_HR hr ON op.id_medic = hr.id_medic
        WHERE op.nume = ? AND op.prenume = ? AND hr.data_angajarii = ?
        """,
        (nume, prenume, data_angajarii),
        kind="UNIQUE CHECK (vertical FK)",
    )
    if rows:
        raise ValueError("Combinatia nume + prenume + data_angajarii exista deja (posibila frauda).")

    exec_sql("S1", "INSERT INTO MEDIC_OP(id_medic, nume, prenume, cod_parafa) VALUES (?, ?, ?, ?)",
             (id_medic, nume, prenume, cod_parafa), kind="INSERT MEDIC_OP @ S1")
    exec_sql("S1", "INSERT INTO MEDIC_HR(id_medic, data_angajarii, salariu) VALUES (?, ?, ?)",
             (id_medic, data_angajarii, salariu), kind="INSERT MEDIC_HR @ S1 (confidential)")

    for n in LOCAL_NODES:
        exec_sql(n, "INSERT INTO MEDIC_OP(id_medic, nume, prenume, cod_parafa) VALUES (?, ?, ?, ?)",
                 (id_medic, nume, prenume, cod_parafa),
                 kind=f"REPLICATION MEDIC_OP -> {n}")


def update_salariu(id_medic: int, salariu_nou: float) -> None:
    """Constraint distribuit: nu permite marirea de salariu daca exista facturi
    restante asociate medicului in oricare dintre nodurile locale."""
    total_restante = 0
    for n in LOCAL_NODES:
        row = query(
            n,
            """
            SELECT COUNT(*) AS c
            FROM FACTURA_LOCAL f
            JOIN PROGRAMARE_LOCAL p ON p.id_programare = f.id_programare
            WHERE p.id_medic = ? AND f.status_plata = 'Restant'
            """,
            (id_medic,),
            kind=f"DISTRIBUTED CHECK @ {n}",
        )
        total_restante += int(row[0]["c"])

    if total_restante > 0:
        raise ValueError(
            f"Marirea salariala este blocata: medicul are {total_restante} facturi restante in retea."
        )

    exec_sql("S1", "UPDATE MEDIC_HR SET salariu = ? WHERE id_medic = ?", (salariu_nou, id_medic),
             kind="UPDATE MEDIC_HR @ S1")


# ---------------------------------------------------------------------------
# Operatii pe PACIENT / PROGRAMARE / FACTURA (fragmentare orizontala)
# ---------------------------------------------------------------------------

def insert_pacient(nume: str, prenume: str, cnp: str, data_nasterii: str, gen: str, regiune: str) -> int:
    if regiune not in REGION_TO_NODE:
        raise ValueError("Regiune invalida (Sud / Vest / Est).")

    catalog = query("S1", "SELECT node FROM CATALOG_GLOBAL WHERE cnp = ?", (cnp,),
                    kind="UNIQUE CNP CHECK @ S1 (catalog global)")
    if catalog:
        raise ValueError(f"CNP {cnp} exista deja in reteaua nationala (filiala {catalog[0]['node']}).")

    node = REGION_TO_NODE[regiune]
    new_id = next_id(node, "seq_pacient")
    exec_sql(
        node,
        "INSERT INTO PACIENTI_LOCAL(id_pacient, nume, prenume, cnp, data_nasterii, gen, regiune) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (new_id, nume, prenume, cnp, data_nasterii, gen, regiune),
        kind=f"INSERT PACIENT @ {node}",
    )
    exec_sql("S1", "INSERT INTO CATALOG_GLOBAL(cnp, node, regiune) VALUES (?, ?, ?)",
             (cnp, node, regiune), kind="UPDATE CATALOG_GLOBAL @ S1")
    return new_id


def insert_programare(id_pacient: int, id_medic: int, id_tratament: int | None,
                      data_ora: str, durata_min: int, status: str,
                      target_node: str | None = None) -> int:
    """Constraint distribuit FK: pacientul trebuie sa existe in oricare nod local."""
    home_node = None
    for n in LOCAL_NODES:
        row = query(n, "SELECT regiune FROM PACIENTI_LOCAL WHERE id_pacient = ?", (id_pacient,),
                    kind=f"DISTRIBUTED FK CHECK PACIENT @ {n}")
        if row:
            home_node = n
            break
    if home_node is None:
        raise ValueError(f"Pacientul {id_pacient} nu exista in reteaua spitalelor.")

    target = target_node or home_node
    if target not in LOCAL_NODES:
        raise ValueError("Nod local invalid pentru programare.")

    if not query("S1", "SELECT 1 FROM MEDIC_OP WHERE id_medic = ?", (id_medic,),
                 kind="DISTRIBUTED FK CHECK MEDIC @ S1"):
        raise ValueError(f"Medicul {id_medic} nu este inregistrat la nivel global.")

    new_id = next_id(target, "seq_programare")
    exec_sql(
        target,
        "INSERT INTO PROGRAMARE_LOCAL(id_programare, id_pacient, id_medic, id_tratament, "
        "data_ora, durata_min, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (new_id, id_pacient, id_medic, id_tratament, data_ora, durata_min, status),
        kind=f"INSERT PROGRAMARE @ {target}",
    )
    return new_id


def insert_factura(id_programare: int, suma: float, status_plata: str,
                   data_emitere: str | None = None) -> int:
    home_node = None
    for n in LOCAL_NODES:
        if query(n, "SELECT 1 FROM PROGRAMARE_LOCAL WHERE id_programare = ?", (id_programare,),
                 kind=f"FK CHECK PROGRAMARE @ {n}"):
            home_node = n
            break
    if home_node is None:
        raise ValueError(f"Programarea {id_programare} nu exista.")

    new_id = next_id(home_node, "seq_factura")
    exec_sql(
        home_node,
        "INSERT INTO FACTURA_LOCAL(id_factura, id_programare, data_emitere, suma, status_plata) "
        "VALUES (?, ?, ?, ?, ?)",
        (new_id, id_programare, data_emitere or datetime.now().strftime("%Y-%m-%d"), suma, status_plata),
        kind=f"INSERT FACTURA @ {home_node}",
    )
    return new_id


def insert_prog_diag(id_programare: int, id_diagnostic: int, este_principal: int) -> int:
    home_node = None
    for n in LOCAL_NODES:
        if query(n, "SELECT 1 FROM PROGRAMARE_LOCAL WHERE id_programare = ?", (id_programare,),
                 kind=f"FK CHECK PROGRAMARE @ {n}"):
            home_node = n
            break
    if home_node is None:
        raise ValueError(f"Programarea {id_programare} nu exista.")
    new_id = next_id(home_node, "seq_prog_diag")
    exec_sql(
        home_node,
        "INSERT INTO PROG_DIAG_LOCAL(id_prog_diag, id_programare, id_diagnostic, este_principal) "
        "VALUES (?, ?, ?, ?)",
        (new_id, id_programare, id_diagnostic, este_principal),
        kind=f"INSERT PROG_DIAG @ {home_node}",
    )
    return new_id


# ---------------------------------------------------------------------------
# Vederi globale (transparenta fragmentarii)
# ---------------------------------------------------------------------------

def view_pacienti_complet(filter_node: str | None = None) -> List[Dict]:
    nodes = (filter_node,) if filter_node else LOCAL_NODES
    rows: List[Dict] = []
    for n in nodes:
        for r in query(n, "SELECT * FROM PACIENTI_LOCAL", kind=f"UNION ALL @ {n} (V_PACIENTI)"):
            d = dict(r)
            d["_node"] = n
            d["_user"] = NODES[n]["user"]
            rows.append(d)
    return rows


def view_programare_complet() -> List[Dict]:
    rows: List[Dict] = []
    for n in LOCAL_NODES:
        for r in query(n, "SELECT * FROM PROGRAMARE_LOCAL", kind=f"UNION ALL @ {n} (V_PROGRAMARE)"):
            d = dict(r)
            d["_node"] = n
            rows.append(d)
    return rows


def view_factura_complet() -> List[Dict]:
    rows: List[Dict] = []
    for n in LOCAL_NODES:
        for r in query(n, "SELECT * FROM FACTURA_LOCAL", kind=f"UNION ALL @ {n} (V_FACTURA)"):
            d = dict(r)
            d["_node"] = n
            rows.append(d)
    return rows


def view_medic_complet() -> List[Dict]:
    """Joncțiune verticala: MEDIC_OP (replicat / S1) cu MEDIC_HR (doar S1)."""
    op = query("S1", "SELECT id_medic, nume, prenume, cod_parafa FROM MEDIC_OP",
               kind="VERTICAL JOIN: MEDIC_OP @ S1")
    hr = query("S1", "SELECT id_medic, data_angajarii, salariu FROM MEDIC_HR",
               kind="VERTICAL JOIN: MEDIC_HR @ S1")
    hr_idx = {r["id_medic"]: dict(r) for r in hr}
    rows: List[Dict] = []
    for r in op:
        d = dict(r)
        if r["id_medic"] in hr_idx:
            d.update(hr_idx[r["id_medic"]])
        rows.append(d)
    return rows


# ---------------------------------------------------------------------------
# Cererea complexa - 3 strategii de optimizare
# ---------------------------------------------------------------------------

def report_diabet_sequential(diagnostic_name: str = "Diabet", year: int | None = None) -> Dict:
    """Strategia 1 (RBO-like / nested loops sequential):

    Centralizam absolut toate randurile relevante pe nodul Global, apoi
    facem joncțiunile in memorie ca si cum am avea o singura baza de date.
    Aceasta strategie este folosita pentru comparare - este lenta deoarece
    transfera mult mai multe date prin retea.
    """
    with timed() as t:
        progs: List[Dict] = []
        diags: List[Dict] = []
        facts: List[Dict] = []
        for n in LOCAL_NODES:
            for r in query(n, "SELECT * FROM PROGRAMARE_LOCAL", kind=f"FULL FETCH PROGRAMARE @ {n}"):
                d = dict(r); d["_node"] = n; progs.append(d)
            for r in query(n, "SELECT * FROM PROG_DIAG_LOCAL", kind=f"FULL FETCH PROG_DIAG @ {n}"):
                d = dict(r); d["_node"] = n; diags.append(d)
            for r in query(n, "SELECT * FROM FACTURA_LOCAL", kind=f"FULL FETCH FACTURA @ {n}"):
                d = dict(r); d["_node"] = n; facts.append(d)

        diag_catalog = {r["id_diagnostic"]: dict(r) for r in
                        query("S1", "SELECT * FROM DIAGNOSTIC", kind="REPLICATED READ DIAGNOSTIC @ S1")}
        medic_op = {r["id_medic"]: dict(r) for r in
                    query("S1", "SELECT * FROM MEDIC_OP", kind="REPLICATED READ MEDIC_OP @ S1")}
        medic_hr = {r["id_medic"]: dict(r) for r in
                    query("S1", "SELECT * FROM MEDIC_HR", kind="READ MEDIC_HR @ S1")}

        target_diag_ids = {did for did, d in diag_catalog.items()
                           if diagnostic_name.lower() in d["nume"].lower()}
        prog_with_diag: Dict[int, str] = {}
        for d in diags:
            if d["id_diagnostic"] in target_diag_ids:
                prog_with_diag[d["id_programare"]] = d["_node"]

        per_medic: Dict[int, Dict] = {}
        for p in progs:
            if p["id_programare"] in prog_with_diag and p["status"] == "Finalizat":
                if year is not None and not p["data_ora"].startswith(str(year)):
                    continue
                m = per_medic.setdefault(p["id_medic"], {"pacienti": set(), "total": 0.0})
                m["pacienti"].add(p["id_pacient"])

        prog_to_factura: Dict[int, float] = {f["id_programare"]: f["suma"] for f in facts}
        for pid, node in prog_with_diag.items():
            for p in progs:
                if p["id_programare"] == pid and p["id_medic"] in per_medic:
                    per_medic[p["id_medic"]]["total"] += float(prog_to_factura.get(pid, 0))
                    break

        out: List[Dict] = []
        for id_medic, agg in per_medic.items():
            op = medic_op.get(id_medic, {})
            hr = medic_hr.get(id_medic, {})
            out.append({
                "id_medic": id_medic,
                "nume": op.get("nume"),
                "prenume": op.get("prenume"),
                "salariu": hr.get("salariu"),
                "nr_pacienti": len(agg["pacienti"]),
                "total_facturat": round(agg["total"], 2),
            })
        out.sort(key=lambda r: r["total_facturat"], reverse=True)

    return {
        "strategy": "Sequential / Nested Loops (RBO-like)",
        "description": "Toate randurile sunt aduse in memorie pe coordonator si JOIN-uite secvential.",
        "rows": out,
        "elapsed_ms": t["elapsed_ms"],
        "network_payload_rows": len(progs) + len(diags) + len(facts),
    }


def report_diabet_hash_join(diagnostic_name: str = "Diabet", year: int | None = None) -> Dict:
    """Strategia 2 (CBO / Hash Join): preluam date locale dar agregam mai mult
    pe nodul global; tot transferam prin retea, dar folosim hash maps pentru
    joncțiuni eficiente."""
    with timed() as t:
        diag_ids = [r["id_diagnostic"] for r in
                    query("S1",
                          "SELECT id_diagnostic FROM DIAGNOSTIC WHERE LOWER(nume) LIKE ?",
                          (f"%{diagnostic_name.lower()}%",),
                          kind="HASH JOIN STEP 1: filter DIAGNOSTIC @ S1")]
        if not diag_ids:
            return {"strategy": "Hash Join (CBO-like)", "rows": [], "elapsed_ms": t["elapsed_ms"],
                    "network_payload_rows": 0, "description": "Niciun diagnostic gasit."}

        placeholders = ",".join(["?"] * len(diag_ids))
        agg_per_medic: Dict[int, Dict] = {}
        payload_rows = 0

        for n in LOCAL_NODES:
            sql = f"""
                SELECT p.id_medic, p.id_pacient, p.id_programare, f.suma
                FROM PROGRAMARE_LOCAL p
                JOIN PROG_DIAG_LOCAL d ON d.id_programare = p.id_programare
                LEFT JOIN FACTURA_LOCAL f ON f.id_programare = p.id_programare
                WHERE d.id_diagnostic IN ({placeholders})
                  AND p.status = 'Finalizat'
                  {"AND substr(p.data_ora, 1, 4) = ?" if year else ""}
            """
            params = list(diag_ids) + ([str(year)] if year else [])
            local_rows = query(n, sql, params, kind=f"HASH JOIN STEP 2: aggregate @ {n}")
            payload_rows += len(local_rows)
            for r in local_rows:
                m = agg_per_medic.setdefault(r["id_medic"], {"pacienti": set(), "total": 0.0})
                m["pacienti"].add(r["id_pacient"])
                m["total"] += float(r["suma"] or 0)

        medic_op = {r["id_medic"]: dict(r) for r in
                    query("S1", "SELECT id_medic, nume, prenume FROM MEDIC_OP",
                          kind="HASH BUILD MEDIC_OP @ S1")}
        medic_hr = {r["id_medic"]: dict(r) for r in
                    query("S1", "SELECT id_medic, salariu FROM MEDIC_HR",
                          kind="HASH BUILD MEDIC_HR @ S1")}

        out: List[Dict] = []
        for id_medic, agg in agg_per_medic.items():
            op = medic_op.get(id_medic, {})
            hr = medic_hr.get(id_medic, {})
            out.append({
                "id_medic": id_medic,
                "nume": op.get("nume"),
                "prenume": op.get("prenume"),
                "salariu": hr.get("salariu"),
                "nr_pacienti": len(agg["pacienti"]),
                "total_facturat": round(agg["total"], 2),
            })
        out.sort(key=lambda r: r["total_facturat"], reverse=True)

    return {
        "strategy": "Hash Join (CBO-like)",
        "description": "Filtrare locala + hash join in memorie pe nodul global.",
        "rows": out,
        "elapsed_ms": t["elapsed_ms"],
        "network_payload_rows": payload_rows,
    }


def report_diabet_parallel_semijoin(diagnostic_name: str = "Diabet", year: int | None = None) -> Dict:
    """Strategia 3 (PARALLEL + Semi-Join): fiecare nod local agrega complet local
    si trimite doar (id_medic, nr_pacienti, sum_facturi) - lista scurta.
    Apoi S1 face ultimul JOIN cu MEDIC_OP/MEDIC_HR doar pentru ID-urile primite.
    """
    import concurrent.futures as cf

    diag_ids = [r["id_diagnostic"] for r in
                query("S1",
                      "SELECT id_diagnostic FROM DIAGNOSTIC WHERE LOWER(nume) LIKE ?",
                      (f"%{diagnostic_name.lower()}%",),
                      kind="PARALLEL STEP 1: filter DIAGNOSTIC @ S1")]
    if not diag_ids:
        return {"strategy": "Parallel + Semi-Join", "rows": [], "elapsed_ms": 0,
                "network_payload_rows": 0, "description": "Niciun diagnostic gasit."}

    placeholders = ",".join(["?"] * len(diag_ids))

    def local_agg(n: str):
        sql = f"""
            SELECT p.id_medic,
                   COUNT(DISTINCT p.id_pacient) AS nr_pacienti,
                   COALESCE(SUM(f.suma), 0)    AS total_facturat
            FROM PROGRAMARE_LOCAL p
            JOIN PROG_DIAG_LOCAL d ON d.id_programare = p.id_programare
            LEFT JOIN FACTURA_LOCAL f ON f.id_programare = p.id_programare
            WHERE d.id_diagnostic IN ({placeholders})
              AND p.status = 'Finalizat'
              {"AND substr(p.data_ora, 1, 4) = ?" if year else ""}
            GROUP BY p.id_medic
        """
        params = list(diag_ids) + ([str(year)] if year else [])
        return [dict(r) for r in query(n, sql, params, kind=f"PARALLEL AGG @ {n}")]

    start = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=len(LOCAL_NODES)) as ex:
        futures = {n: ex.submit(local_agg, n) for n in LOCAL_NODES}
        partial = {n: f.result() for n, f in futures.items()}

    agg_per_medic: Dict[int, Dict] = {}
    payload_rows = 0
    for n, rows in partial.items():
        payload_rows += len(rows)
        for r in rows:
            m = agg_per_medic.setdefault(r["id_medic"], {"nr": 0, "total": 0.0})
            m["nr"] += int(r["nr_pacienti"])
            m["total"] += float(r["total_facturat"])

    if not agg_per_medic:
        elapsed = round((time.perf_counter() - start) * 1000, 3)
        return {"strategy": "Parallel + Semi-Join", "rows": [], "elapsed_ms": elapsed,
                "network_payload_rows": payload_rows,
                "description": "Niciun medic nu indeplineste criteriile."}

    ids = list(agg_per_medic.keys())
    ph = ",".join(["?"] * len(ids))
    medic_op = {r["id_medic"]: dict(r) for r in query(
        "S1", f"SELECT id_medic, nume, prenume FROM MEDIC_OP WHERE id_medic IN ({ph})",
        ids, kind="SEMI-JOIN MEDIC_OP @ S1")}
    medic_hr = {r["id_medic"]: dict(r) for r in query(
        "S1", f"SELECT id_medic, salariu FROM MEDIC_HR WHERE id_medic IN ({ph})",
        ids, kind="SEMI-JOIN MEDIC_HR @ S1")}

    out: List[Dict] = []
    for id_medic, agg in agg_per_medic.items():
        op = medic_op.get(id_medic, {})
        hr = medic_hr.get(id_medic, {})
        out.append({
            "id_medic": id_medic,
            "nume": op.get("nume"),
            "prenume": op.get("prenume"),
            "salariu": hr.get("salariu"),
            "nr_pacienti": agg["nr"],
            "total_facturat": round(agg["total"], 2),
        })
    out.sort(key=lambda r: r["total_facturat"], reverse=True)
    elapsed = round((time.perf_counter() - start) * 1000, 3)

    return {
        "strategy": "Parallel Execution + Semi-Join",
        "description": "Agregari executate paralel pe S2/S3/S4; doar id_medic + agregari ajung pe S1.",
        "rows": out,
        "elapsed_ms": elapsed,
        "network_payload_rows": payload_rows,
    }


# ---------------------------------------------------------------------------
# Seeders / populare initiala
# ---------------------------------------------------------------------------

def seed_if_empty() -> bool:
    """Daca PACIENTI_LOCAL pe S2 e gol, populeaza demo data."""
    cnt = query("S2", "SELECT COUNT(*) AS c FROM PACIENTI_LOCAL", kind="SEED CHECK")[0]["c"]
    if cnt > 0:
        return False

    today = datetime(2026, 5, 5)

    sectii = [
        (1, "Cardiologie", 2, 30),
        (2, "Neurologie", 3, 25),
        (3, "Pediatrie", 1, 40),
        (4, "Endocrinologie", 4, 20),
        (5, "Ortopedie", 2, 35),
    ]
    for s in sectii:
        replicate_to_all("SECTIE", ("id_sectie", "denumire", "etaj", "numar_paturi"), s)

    specs = [
        (1, "Medic generalist", "Medicina interna"),
        (2, "Cardiolog", "Boli ale inimii si vaselor"),
        (3, "Neurolog", "Boli ale sistemului nervos"),
        (4, "Diabetolog", "Diabet si boli endocrine"),
        (5, "Ortoped", "Aparatul locomotor"),
    ]
    for s in specs:
        replicate_to_all("SPECIALIZARE", ("id_specializare", "denumire", "descriere"), s)

    diag = [
        (1, "E11", "Diabet zaharat tip 2", "Mediu"),
        (2, "I10", "Hipertensiune arteriala esentiala", "Mediu"),
        (3, "I21", "Infarct miocardic acut", "Critic"),
        (4, "G40", "Epilepsie", "Critic"),
        (5, "J45", "Astm bronsic", "Mediu"),
        (6, "M54", "Lombalgie", "Scazut"),
        (7, "E10", "Diabet zaharat tip 1", "Critic"),
        (8, "K29", "Gastrita", "Scazut"),
    ]
    for d in diag:
        replicate_to_all("DIAGNOSTIC", ("id_diagnostic", "cod_boala", "nume", "severitate"), d)

    trat = [
        (1, "Metformin 850mg", "medicamentos", 35.0),
        (2, "Insulinoterapie", "medicamentos", 220.0),
        (3, "Bypass coronarian", "chirurgical", 9500.0),
        (4, "Beta-blocant", "medicamentos", 45.0),
        (5, "Kinetoterapie", "fizioterapie", 150.0),
        (6, "Inhalator salbutamol", "medicamentos", 30.0),
    ]
    for t in trat:
        replicate_to_all("TRATAMENT", ("id_tratament", "denumire", "tip", "cost_referinta"), t)

    medics = [
        (1, "Popescu", "Andrei",  "PAR-1001", "2015-03-12", 12500.0),
        (2, "Ionescu", "Maria",   "PAR-1002", "2018-06-01", 11200.0),
        (3, "Georgescu", "Mihai", "PAR-1003", "2012-09-21", 14800.0),
        (4, "Marin", "Elena",     "PAR-1004", "2020-01-15", 9800.0),
        (5, "Stoica", "Radu",     "PAR-1005", "2010-11-04", 16500.0),
        (6, "Dumitrescu", "Ana",  "PAR-1006", "2017-05-30",  9400.0),
    ]
    for m in medics:
        insert_medic(*m)

    medic_specs = [
        (1, 1, 2), (2, 2, 4), (3, 3, 3), (4, 4, 1),
        (5, 5, 2), (6, 5, 5), (7, 6, 4),
    ]
    for ms in medic_specs:
        replicate_to_all("MEDIC_SPECIALIZARI", ("id_medic_spec", "id_medic", "id_specializare"), ms)

    medic_sectii = [
        (1, 1, 1), (2, 2, 4), (3, 3, 2), (4, 4, 3),
        (5, 5, 1), (6, 5, 5), (7, 6, 4),
    ]
    for ms in medic_sectii:
        replicate_to_all("MEDIC_SECTII", ("id_medic_sectii", "id_medic", "id_sectie"), ms)

    pacienti = [
        ("Radu",      "Cristian", "1900101000001", "1985-04-12", "Masculin", "Sud"),
        ("Mihaila",   "Ioana",    "2900101000002", "1990-07-22", "Feminin",  "Sud"),
        ("Stan",      "George",   "1900101000003", "1978-12-03", "Masculin", "Sud"),
        ("Vasile",    "Daniela",  "2900101000004", "1995-01-19", "Feminin",  "Sud"),
        ("Munteanu",  "Adrian",   "1900101000005", "1982-08-30", "Masculin", "Vest"),
        ("Dobre",     "Larisa",   "2900101000006", "1992-11-11", "Feminin",  "Vest"),
        ("Lazar",     "Florin",   "1900101000007", "1975-05-25", "Masculin", "Vest"),
        ("Tudor",     "Bianca",   "2900101000008", "2001-09-09", "Feminin",  "Est"),
        ("Petre",     "Catalin",  "1900101000009", "1988-02-17", "Masculin", "Est"),
        ("Neagu",     "Roxana",   "2900101000010", "1996-06-06", "Feminin",  "Est"),
        ("Constantin","Vlad",     "1900101000011", "1970-10-10", "Masculin", "Est"),
    ]
    pacient_ids: Dict[str, int] = {}
    for p in pacienti:
        pid = insert_pacient(*p)
        pacient_ids[p[2]] = pid

    programari = [
        # CNP, id_medic, id_tratament, data_ora, status, diag, principal, suma, status_plata
        ("1900101000001", 2, 1, "2026-02-12 10:00", "Finalizat", 1, 1, 350.0, "Platit"),
        ("1900101000001", 2, 1, "2025-09-08 10:30", "Finalizat", 1, 1, 320.0, "Platit"),
        ("2900101000002", 1, 2, "2026-01-05 09:00", "Finalizat", 2, 1, 180.0, "Platit"),
        ("1900101000003", 3, 4, "2025-11-22 11:15", "Finalizat", 3, 1, 5400.0, "Restant"),
        ("2900101000004", 4, 1, "2026-03-15 14:00", "Finalizat", 1, 1, 290.0, "Platit"),
        ("1900101000005", 5, 3, "2025-12-01 08:30", "Finalizat", 3, 1, 9200.0, "Platit"),
        ("2900101000006", 2, 1, "2026-02-20 13:45", "Finalizat", 1, 1, 410.0, "Restant"),
        ("1900101000007", 6, 1, "2026-04-02 09:30", "Finalizat", 7, 1, 270.0, "Platit"),
        ("2900101000008", 5, 5, "2025-10-19 16:00", "Finalizat", 6, 1, 220.0, "Platit"),
        ("1900101000009", 2, 2, "2026-01-30 12:30", "Finalizat", 1, 1, 480.0, "Platit"),
        ("2900101000010", 4, 1, "2026-03-08 11:00", "Finalizat", 1, 1, 305.0, "Platit"),
        ("1900101000011", 6, 6, "2026-04-14 10:20", "Finalizat", 5, 1, 180.0, "Platit"),
        ("2900101000004", 6, 1, "2026-04-25 15:00", "Programat", None, None, None, None),
    ]
    for cnp, idm, idt, dora, st, did, princ, suma, sp in programari:
        pid = pacient_ids[cnp]
        prog_id = insert_programare(pid, idm, idt, dora, 30, st)
        if did is not None:
            insert_prog_diag(prog_id, did, princ)
        if suma is not None:
            insert_factura(prog_id, suma, sp, dora.split(" ")[0])

    return True
